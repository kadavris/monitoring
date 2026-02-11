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
import time


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
        self._debug: bool = debug
        self._pipe: subprocess.Popen | None = None

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

        sender_output = None if self._debug or self._cfg_invoke.find('--debug') != -1 else subprocess.DEVNULL
        # default bufsize may gobble a whole loop of data and do nothing till the next
        self._pipe = subprocess.Popen(shlex.split(self._cfg_invoke), bufsize=1,
                                      stdin=subprocess.PIPE, stdout=sender_output, stderr=sender_output,
                                      text=True)

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


    ########################################
    def terminate(self) -> None:
        """Ending the session, despawning sender process"""
        try:
            self._pipe.communicate(input='\n\n{ "cmd":"exit" }\n')
            self._pipe.wait(timeout=15.0)
            self._pipe.terminate()
            self._pipe = None
        except Exception:
            pass


    ########################################
    def receive(self) -> str | None:
        if not self._pipe or self._pipe.poll():
            return None

        answer = None
        if self._pipe.stdout \
            and select.select([self._pipe.stdout], [None], [None], 3)[0][0] > 0:
                answer = self._pipe.stdout.readline()

                if self._debug:
                    print('< Answer:', answer)

        return answer


    ########################################
    def _get_rc_answer(self) -> str | None:
        if not self._pipe or self._pipe.poll():
            return None

        try_count = 0
        while True:
            try_count += 1

            answer = self.receive()
            if answer and -1 != answer.find('"rc":'):
                return answer

            if try_count < 3:
                time.sleep(3.0)  # let it process then
                continue

            if self._debug:
                print(time.localtime(), "!ERROR processing packet", file=sys.stderr)
                break

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
                print("!!! Respawning.", file=sys.stderr)
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
                        print("! Got improper answer: ", answer, file=sys.stderr)
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
        self._send_prepared(f'{{ "mpublish":"{stop_word}", "retain":{retain},'
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
        self.send('{"publish":"', ''.join(msg), f'", "retain":{retain}, "topics":["{topic}"]}}')

