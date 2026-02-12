"""
This module is a part of the monitoring toolset from GitHub/kadavris/monitoring
The main feature is the KMQTT class that provides simple interface to the MQTT agent
"""
import json
import re
import select
import shlex
import subprocess
import sys


class KMQTT:
    """
    Provides interface to an agent that will send our messages to MQTT.
    Actually it will follow the protocol for mqtt-tools from the GitHub/kadavris/mqtt-tools repo.
    The interface is simple. Use:
      - send() to send a prepared message
      - send_json_short() to send a short message with MQTT headers
      - send_json_long() to send a long message with MQTT headers
    """
    def __init__(self, cfg_invoke: str, critical: bool=True, debug: bool = False) -> None:
        self._critical: bool = critical
        self._cfg_invoke: str = cfg_invoke
        self._debug: bool = debug or self._cfg_invoke.find('--debug')
        self._pipe: subprocess.Popen | None = None
        self._poller = None  # for systems that understand poll/epoll

        self._spawn_sender(True)


    ########################################
    def _spawn_sender(self, force: bool = False) -> None:
        """
        Will spawn sender process, checking for various problems
        :return: None
        """
        if self._pipe and not self._pipe.poll() and not force:  # skip respawning on a live thing
            return

        if self._debug:
            print("+ Spawning sender process:", self._cfg_invoke, file=sys.stderr)

        # default bufsize may gobble a whole loop of data and do nothing till the next
        self._pipe = subprocess.Popen(shlex.split(self._cfg_invoke), bufsize=1, encoding='utf-8',
                                      # text=True, universal_newlines=True,
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=None if self._debug else subprocess.DEVNULL)

        if not self._pipe:
            print('! ERROR running ', self._cfg_invoke, file=sys.stderr)
            if self._critical:
                sys.exit(1)

        if self._pipe.poll():  # poll() return None if process is still there
            print('! Problem running ', self._pipe.args, ": exited ",
                  ("abnormally" if self._pipe.returncode > 0 else "gracefully"),
                  "with rc:", self._pipe.returncode, file=sys.stderr)
            if self._critical:
                sys.exit(1)

        if sys.platform.startswith("linux"):
            self._poller = select.poll()
            self._poller.register(self._pipe.stdout.fileno(),
                                  select.EPOLLIN | select.EPOLLERR | select.EPOLLHUP | select.EPOLLRDHUP)


    ########################################
    def terminate(self) -> None:
        """Ending the session, despawning sender process"""
        try:
            self._pipe.communicate(input='\n\n{ "cmd":"exit" }\n')
        except:
            pass

        try:
            self._pipe.wait(timeout=5.0)
        except:
            pass

        try:
            self._pipe.terminate()
        except:
            pass

        self._pipe = None


    ########################################
    def receive(self) -> str | None:
        """
        Tries to receive a message from the sender process
        :return: None in case of problems or str if answered to
        """
        if not self._pipe or self._pipe.poll():
            return None

        answer = None
        ready = False
        if sys.platform.startswith("linux"):
            evt = self._poller.poll(3000)
            print(f"poll: evt:{evt}")
            if len(evt) != 0:
                print(f"poll: fd:{evt[0][0]}: state: {evt[0][1]}")
                if evt[0][1] & select.EPOLLIN:
                    ready = True
                elif evt[0][1]:  # error conditions
                    self.terminate()

        elif sys.platform.startswith("cygwin") or sys.platform.startswith("win"):
            slists = select.select([self._pipe.stdout], [],
                                   [self._pipe.stdout], 3.0)
            if len(slists[0]) != 0 and slists[0][0]:
                ready = True

            elif len(slists[2]) != 0 and slists[2][0] != 0:
                if self._debug:
                    print('! pipe error')

                self.terminate()

        if ready:
            answer = self._pipe.stdout.readline()

            if self._debug:
                print('< Answer:', answer)

        return answer


    ########################################
    def _get_rc_answer(self) -> str | None:
        if not self._pipe or self._pipe.poll():
            return None

        try_count = 0
        while try_count <= 3:
            try_count += 1

            answer = self.receive()
            if answer and -1 != answer.find('"rc":'):
                return answer

            if self._debug:
                print("! sender says:", answer, file=sys.stderr)

        if self._debug:
            print("! ERROR processing RC packet from sender", file=sys.stderr)

        return None


    ########################################
    def _send_prepared(self, msg: str) -> None:
        """
        Sends completely ready message to mqtt agent
        :param msg: str: sent as is
        :return: None
        """
        try_number = 0
        while True:
            try_number += 1
            if try_number > 3:
                if not self._critical:
                    return

                try_number = 1
                if self._debug:
                    print("! Respawning sender.", file=sys.stderr)
                self._spawn_sender(True)

            if not self._pipe or self._pipe.poll():  # check if it is still alive (not None)
                self._spawn_sender(True)
                continue

            if self._debug:
                print('> Sending:', msg)

            try:
                self._pipe.stdin.write(msg)
                self._pipe.stdin.write("\n")
            except Exception:
                if self._debug:
                    exc_type, exc_val, traceback = sys.exc_info()
                    print("! Sending failed (", exc_val, ")", file=sys.stderr)
                continue

            answer = self._get_rc_answer()
            if not answer:
                continue

            try:
                j = json.loads(answer)
                if not "rc" in j:
                    if self._debug:
                        print("! Got an improper answer: ", answer, file=sys.stderr)
                    break

                if j["rc"] != 0:
                    if self._debug:
                        print("! Got RC:", j['rc'], "->", j['message'], file=sys.stderr)

            except Exception:
                if self._debug:
                    print("! Got invalid JSON:", answer, file=sys.stderr)
                return

            break


    ########################################
    def send(self, *in_msg: str) -> None:
        """
        Sends a plain message to the spawned mqtt agent. Fixes it to be one-line.
        :param in_msg: list of strings: parts of the whole message
        :return: None
        """

        # our standard sending tool expect either one-line JSON or back-slash terminated multiline one
        self._send_prepared(re.sub(r"([^\\])\n", "\\1\\\n", "".join(in_msg)))


    ########################################
    def send_json_long(self, topic: str, *msg: str, retain: bool=False,
                  stop_word: str = "\x01RlVDS1JVU1NJQQ\x02") -> None:
        """
        Sends multiline message
        :param topic: topic name
        :param msg: list of strings
        :param retain: bool: MQTT retain flag
        :param stop_word: str: optional stop word to use as an EOM indicator
        :return: None
        """
        self._send_prepared(f'{{ "mpublish":"{stop_word}", "retain":{str(retain).lower()},'
                         f' "topics":["{topic}"] }}\n' + ''.join(msg) + stop_word)


    ########################################
    def send_json_short(self, topic: str, *msg: str, retain: bool=False) -> None:
        """
        Posts a short or one-line message to a single topic
        :param topic: str. topic name
        :param msg: str list
        :param retain: bool: MQTT retain flag
        :return:
        """
        self.send('{"publish":"', ''.join(msg),
                        f'", "retain":{str(retain).lower()}, "topics":["{topic}"]}}')

