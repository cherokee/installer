#!/usr/bin/env python

# -*- coding: utf-8 -*-
#
# Cherokee-admin
#
# Authors:
#      Alvaro Lopez Ortega <alvaro@alobbs.com>
#
# Copyright (C) 2001-2011 Alvaro Lopez Ortega
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of version 2 of the GNU General Public
# License as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.
#

import re
import os
import sys
import glob
import subprocess

BUILD_DIR          = "/var/tmp/cherokee-build"
URL_LATEST_RELEASE = "http://www.cherokee-project.com/cherokee-latest-tarball"
PREFIX             = "/opt/cherokee"

PHASE_DOWNLOAD = 1
PHASE_UNPACK   = 2
PHASE_COMPILE  = 3
PHASE_INSTALL  = 4
PHASE_INITD    = 5
PHASE_REPORT   = 6


# Texts
#
LAUNCHD_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>org.cherokee.webserver</string>
  <key>RunAtLoad</key><true/>
  <key>ProgramArguments</key><array>
     <string>%(PREFIX)s/sbin/cherokee</string>
  </array>
  <key>UserName</key>
  <string>root</string>
</dict>
</plist>
"""

INITD_SH = """\
#!/bin/sh -e

PATH=/sbin:/bin:/usr/sbin:/usr/bin:%(PREFIX)s/sbin:%(PREFIX)s/bin

DAEMON=%(PREFIX)s/sbin/cherokee
NAME=cherokee
PIDFILE=%(PREFIX)s/var/run/cherokee.pid

set -e
test -x $DAEMON || exit 0

case "$1" in
start)
   %(PREFIX)s/sbin/cherokee -d
   ;;

stop)
   if [ -f $PIDFILE ]; then
        PID=$(cat $PIDFILE)
        kill $PID
   fi
   ;;

restart)
   $0 stop
   sleep 1
   $0 start
   ;;

reload|force-reload)
   printf "Reloading web server: %%s\t" "$NAME"
   if [ -f $PIDFILE ]; then
        PID=$(cat $PIDFILE)
        if ps p $PID | grep $NAME >/dev/null 2>&1; then
           kill -HUP $PID
        else
           echo "PID present, but $NAME not found at PID $PID - Cannot reload"
           exit 1
        fi
   else
        echo "No PID file present for $NAME - Cannot reload"
        exit 1
   fi
   ;;

status)
   printf "%%s web server status:\t" "$NAME"
   if [ -e $PIDFILE ] ; then
       PROCNAME=$(ps -p $(cat $PIDFILE) -o comm=)
       if [ "x$PROCNAME" = "x" ]; then
            printf "Not running, but PID file present \t"
       else
            if [ "$PROCNAME" = "$NAME" ]; then
                 printf "Running\t"
            else
                 printf "PID file points to process '%%s', not '%%s'\t" "$PROCNAME" "$NAME"
            fi
       fi
   else
       if PID=$(pidofproc cherokee); then
            printf "Running (PID %%s), but PIDFILE not present\t" "$PID"
       else
            printf "Not running\t"
       fi
   fi
   ;;

*)
   N=/etc/init.d/$NAME
   echo "Usage: $N {start|stop|restart|reload|force-reload|status}" >&2
   exit 1
   ;;
esac

if [ $? = 0 ]; then
    echo .
    exit 0
else
    echo failed
    exit 1
fi
exit 0
"""


# Globals
#
start_at = PHASE_DOWNLOAD


# ANSI Colors
#
ESC   = chr(27) + '['
RESET = '%s0m' %(ESC)

def green (s):  return ESC + '0;32m' + s + RESET
def red (s):    return ESC + '0;31m' + s + RESET
def yellow (s): return ESC + '1;33m' + s + RESET
def blue (s):   return ESC + '0;34m' + s + RESET


# Utilities
#
def exe (cmd, colorer=lambda x: x, cd=None, stdin=None, return_fatal=True):
    print (yellow(cmd))

    stdout = ''

    kwargs = {'shell': True, 'stdout': subprocess.PIPE, 'cwd': cd}
    if stdin:
        kwargs['stdin'] = subprocess.PIPE

    p = subprocess.Popen (cmd, **kwargs)

    if stdin:
        p.stdin.write (stdin)

    while True:
        line = p.stdout.readline()
        if not line:
            break

        line = line.decode('utf-8')
        stdout += line
        print (colorer (line.rstrip('\n\r')))

    p.wait()

    # Return
    if p.returncode != 0 and return_fatal:
        print ('\n%s: Could not execute: %s' %(red('ERROR'), cmd))

    return {'stdout':  stdout,
            'retcode': p.returncode}

def exe_sudo (cmd, **kwargs):
    command = "sudo -S " + cmd
    return exe (command, **kwargs)


def which (program):
    def is_exe(fpath):
        return os.path.exists(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None

def rm (path):
    return exe ("rm -rf '%s'" %(path), red)

def mkdir (path):
    return exe ("mkdir -p '%s'" %(path), blue)

def download (url, target_file):
    # Wget
    wget_bin = which ('wget')
    if wget_bin:
        ret = exe ("wget '%(url)s' --output-document='%(target_file)s'" %(locals()))
        if ret['retcode'] == 0:
            return

    # Curl
    curl_bin = which ('curl')
    if curl_bin:
        ret = exe ("curl '%(url)s' --output '%(target_file)s'" %(locals()))
        if ret['retcode'] == 0:
            return

    # Python
    import urllib2
    print ("Downloading %s" %(url))
    i = urllib2.urlopen (url)
    o = open (target_file, 'w+')
    o.write (i.read())

def read_input (prompt):
    try:
        # Python 2.x
        return raw_input (prompt)
    except NameError:
        # Python 3.x
        return input (prompt)

def read_yes_no (prompt, empty_is=None):
    while True:
        ret = read_input (prompt).lower()
        if ret in ('y','yes'):
            return True
        if ret in ('n','no'):
            return False
        if not ret and empty_is != None:
            return empty_is

_root_password = None
def get_root_password():
    global _root_password

    while not _root_password:
        _root_password = read_input ("root's password: ")

    return _root_password


def figure_initd_app_level (directory, app, not_found=99):
    files = [x.lower() for x in os.listdir(directory)]
    for filename in files:
        tmp = re.findall (r's(\d+)(.+)', filename)
        if not tmp: continue

        if tmp[0][1] == app:
            return tmp[0][0]

    return not_found


# Cherokee
#
def cherokee_download (tar_file):
    latest_local = os.path.join (BUILD_DIR, "cherokee-latest.tar.gz")

    rm (BUILD_DIR)
    rm (tar_file)
    mkdir (BUILD_DIR)

    download (URL_LATEST_RELEASE, tar_file)


def cherokee_find_unpacked():
    for f in os.listdir (BUILD_DIR):
        fp = os.path.join (BUILD_DIR, f)
        tmp = re.findall (r'cherokee-(\d+\.\d+\.\d+)', f)
        if tmp and os.path.isdir (fp):
            return fp


def cherokee_unpack (latest_local):
    # Unpack
    exe ("gzip -dc '%s' | tar xfv -" %(latest_local), cd=BUILD_DIR)

    # Look for the src directory
    return cherokee_find_unpacked()


def cherokee_compile (src_dir):
    exe ("./configure --prefix='%s'" %(PREFIX), cd=src_dir)
    exe ("make", cd=src_dir)


def cherokee_install (src_dir):
    if os.access (PREFIX, os.W_OK):
        exe ("make install", cd=src_dir)
    else:
        exe_sudo ("make install", cd=src_dir)


def cherokee_set_initd():
    print('')

    proceed = read_yes_no ("Do you want Cherokee to be started at boot time? [Y/n] ", True)
    if not proceed:
        return

    vars = globals()
    vars.update (locals())

    # MacOS X
    if sys.platform == 'darwin':
        tmp_fp   = os.path.join (BUILD_DIR, "launchd-cherokee.plist")
        plist_fp = os.path.join (PREFIX,    "launchd-cherokee.plist")

        # Write the plist file
        txt = LAUNCHD_PLIST %(vars)
        f = open (tmp_fp, 'w+')
        f.write (txt)
        f.close()

        # Permissions
        exe_sudo ("cp '%s' '%s'" %(tmp_fp, plist_fp))
        exe_sudo ("chown root  '%s'" %(plist_fp))
        exe_sudo ("chgrp admin '%s'" %(plist_fp))

        # Let launchd know about it
        exe_sudo ("launchctl load -w '%s'" %(plist_fp))
        exe_sudo ("launchctl start org.cherokee.webserver")
        return

    # Init.d
    if (os.path.isdir ("/etc/init.d") and
        (os.path.isdir ("/etc/rc2.d") or os.path.isdir ("/etc/init.d/rc2.d"))):

        # Figure rc2.d directory
        if os.path.isdir ("/etc/rc2.d"):
            rc2_dir = "/etc/rc2.d"
        elif os.path.isdir ("/etc/init.d/rc2.d"):
            rc2_dir = "/etc/init.d/rc2.d"
        else:
            assert False, "Unknow layout"

        # Build paths
        tmp_fp   = os.path.join (BUILD_DIR, "cherokee.initd")
        sh_fp    = os.path.join (PREFIX,    "cherokee.initd")
        initd_fp = "/etc/init.d/cherokee-opt"

        # Figure rc2.d file level
        level = 99
        for k in ('apache', 'apache2', 'httpd', 'lighttpd', 'nginx'):
            level = min (level, figure_initd_app_level (rc2_dir, k))

        rc2S_fp = os.path.join (rc2_dir, "S%02dcherkee-opt"%(level-1))
        rc2K_fp = os.path.join (rc2_dir, "K%02dcherkee-opt"%(level-1))

        # Preliminary clean up
        exe_sudo ("rm -f '%s' '%s' '%s' '%s' '%s'" %(tmp_fp, sh_fp, initd_fp, rc2S_fp, rc2K_fp))

        # Write the init.d file
        txt = INITD_SH %(vars)
        f = open (tmp_fp, 'w+')
        f.write (txt)
        f.close()

        # Permissions
        exe_sudo ("cp '%s' '%s'" %(tmp_fp, sh_fp))
        exe_sudo ("chown root '%s'" %(sh_fp))
        exe_sudo ("chmod 755 '%s'"  %(sh_fp))

        # Add it
        exe_sudo ("ln -s '%s' '%s'" %(sh_fp, initd_fp))   # /etc/init.d/cherokee   -> /opt/..
        exe_sudo ("ln -s '%s' '%s'" %(initd_fp, rc2S_fp)) # /etc/rc2.d/S99cherokee -> /etc/init.d/..
        exe_sudo ("ln -s '%s' '%s'" %(initd_fp, rc2K_fp)) # /etc/rc2.d/K99cherokee -> /etc/init.d/..


def cherokee_report():
    cherokee_fp = os.path.join (PREFIX, "sbin", "cherokee")

    print (blue ("Technical details:"))
    exe ("%s -i" %(cherokee_fp))

    print (blue ("How to:"))
    print (" - Launch manually the server:      %s/sbin/cherokee -d" %(PREFIX))
    print (" - Launch the administration GUI:   %s/bin/cherokee-admin-launcher" %(PREFIX))



# Main
#
def main():
    tar_file = os.path.join (BUILD_DIR, "cherokee-latest.tar.gz")

    if start_at <= PHASE_DOWNLOAD:
        cherokee_download (tar_file)

    if start_at <= PHASE_UNPACK:
        src_dir = cherokee_unpack (tar_file)
    else:
        src_dir = cherokee_find_unpacked()

    if start_at <= PHASE_COMPILE:
        cherokee_compile (src_dir)

    if start_at <= PHASE_INSTALL:
        cherokee_install (src_dir)

    if start_at <= PHASE_INITD:
        cherokee_set_initd()

    if start_at <= PHASE_REPORT:
        cherokee_report ()


def check_prerequisites():
    assert which ("make"), "Make is required for the compilation"


def process_parameters():
    global start_at

    if '--from-unpack' in sys.argv:
        start_at = PHASE_UNPACK
    if '--from-compile' in sys.argv:
        start_at = PHASE_COMPILE
    if '--from-install' in sys.argv:
        start_at = PHASE_INSTALL
    if '--from-initd' in sys.argv:
        start_at = PHASE_INITD
    if '--from-report' in sys.argv:
        start_at = PHASE_REPORT


if __name__ == '__main__':
    process_parameters()
    check_prerequisites()
    main()
