#!/bin/bash
ps -au | grep 'mqtt.*power' | awk -e '{print $2}' | xargs kill -9 
