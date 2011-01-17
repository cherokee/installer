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
PHASE_INITD    = 4
PHASE_REPORT   = 5


# Texts
#
LAUNCHD_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.octality.cherokee</string>
  <key>RunAtLoad</key><true/>
  <key>WorkingDirectory</key><string>%(PREFIX)s</string>
  <key>ProgramArguments</key><array>
       <string>sbin/cherokee</string>
  </array>
</dict>
</plist>
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
def exe (cmd, colorer=lambda x: x, cd=None, return_fatal=True):
    print (yellow(cmd))

    stdout = ''

    p = subprocess.Popen (cmd, shell=True, stdout=subprocess.PIPE, cwd=cd)
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
        print ('\n%s: Could execute: %s' %(red('ERROR'), cmd))

    return {'stdout':  stdout,
            'retcode': p.returncode}

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
            return True
        if not ret and empty_is != None:
            return empty_is


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

    if os.access (PREFIX, os.W_OK):
        exe ("make install", cd=src_dir)
    else:
        exe ("sudo make install", cd=src_dir)


def cherokee_set_initd():
    print('')

    proceed = read_yes_no ("Do you want Cherokee to be started at boot time? [Y/n] ", True)
    if not proceed:
        return

    vars = globals()
    vars.update (locals())

    if sys.platform == 'darwin':
        plist_fd = os.path.join (PREFIX, "launchd-cherokee.plist")

        # Write the plist file
        txt = LAUNCHD_PLIST %(vars)
        f = open (plist_fd, 'w+')
        f.write (txt)
        f.close()

        # Let launchd know about it
        exe ("launchctl load '%s'" %(plist_fd))
        exe ("launchctl start cherokee")


def cherokee_report():
    cherokee_fp = os.path.join (PREFIX, "sbin", "cherokee")
    exe ("%s -i" %(cherokee_fp), green)



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
    if '--from-initd' in sys.argv:
        start_at = PHASE_INITD
    if '--from-report' in sys.argv:
        start_at = PHASE_REPORT


if __name__ == '__main__':
    process_parameters()
    check_prerequisites()
    main()
