#!/usr/bin/env python

# -*- coding: utf-8 -*-
#
# Cherokee easy-install script
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
import time
import stat
import subprocess

BUILD_DIR            = "/var/tmp/cherokee-build"
URL_LATEST_RELEASE   = "http://www.cherokee-project.com/cherokee-latest-tarball"
URL_SNAPSHOT_RELEASE = "http://www.cherokee-project.com/download/trunk/cherokee-latest-svn.tar.gz"
PREFIX_STANDARD      = "/opt/cherokee"
PREFIX_DEVEL         = "/opt/cherokee-dev"

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
     <string>%(prefix)s/sbin/cherokee</string>
  </array>
  <key>UserName</key>
  <string>root</string>
</dict>
</plist>
"""

SOLARIS_SVC = """\
<?xml version="1.0"?>
<!DOCTYPE service_bundle SYSTEM "/usr/share/lib/xml/dtd/service_bundle.dtd.1">

<service_bundle type='manifest' name='cherokee'>
  <service name='network/http' type='service' version='1'>
    <instance name='cherokee' enabled='true'>

      <dependency name='loopback' grouping='require_all' restart_on='error' type='service'>
	<service_fmri value='svc:/network/loopback:default'/>
      </dependency>

      <dependency name='physical' grouping='optional_all' restart_on='error' type='service'>
	<service_fmri value='svc:/network/physical:default'/>
      </dependency>

      <exec_method type='method' name='start' exec='%(prefix)s/sbin/cherokee -d' timeout_seconds='60'>
	<method_context><method_credential user='root' group='root' /></method_context>
      </exec_method>

      <exec_method type='method' name='stop' exec='kill `cat %(prefix)s/var/run/cherokee.pid`' timeout_seconds='60'>
	<method_context><method_credential user='root' group='root' /></method_context>
      </exec_method>

      <exec_method type='method' name='refresh' exec='kill -HUP `cat %(prefix)s/var/run/cherokee.pid`' timeout_seconds='60'>
	<method_context><method_credential user='root' group='root' /></method_context>
      </exec_method>

      <property_group name='startd' type='framework'>
	<propval name='duration' type='astring' value='contract'/>
	<propval name='ignore_error' type='astring' value='core,signal' />
      </property_group>

    </instance>

    <template>
      <common_name><loctext xml:lang='C'>Advanced and Fast Web Server</loctext></common_name>
      <documentation>
	<doc_link name='www.cherokee-project.com' uri='http://www.cherokee-project.com/doc/' />
      </documentation>
    </template>
  </service>
</service_bundle>
"""

INITD_SH = """\
#!/bin/sh -e

PATH=/sbin:/bin:/usr/sbin:/usr/bin:%(prefix)s/sbin:%(prefix)s/bin

DAEMON=%(prefix)s/sbin/cherokee
NAME=cherokee
PIDFILE=%(prefix)s/var/run/cherokee.pid

set -e
test -x $DAEMON || exit 0

case "$1" in
start)
   %(prefix)s/sbin/cherokee -d
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

BSD_INIT = """\
#!/bin/sh

. /etc/rc.subr

name="cherokee"
rcvar="`set_rcvar`"
command="%(prefix)s/sbin/cherokee"

load_rc_config $name
command_args="-d"

run_rc_command "$1"
"""


# Globals
#
prefix            = PREFIX_STANDARD
start_at          = PHASE_DOWNLOAD
download_snapshot = False
devel_build       = False


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
def FATAL_error (error, retcode=1):
    print (red(error))
    sys.exit (retcode)

def exe (cmd, colorer=lambda x: x, cd=None, stdin=None, return_fatal=True):
    print (yellow(cmd))

    stdout = ''

    kwargs = {'shell': True, 'stdout': subprocess.PIPE, 'cwd': cd}
    if stdin:
        kwargs['stdin'] = subprocess.PIPE

    p = subprocess.Popen (cmd, **kwargs)

    if stdin:
        try:
            p.stdin.write (stdin)
            p.stdin.close()
        except IOError:
            pass

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

_root_password = None
def get_root_password():
    global _root_password

    while not _root_password:
        _root_password = read_input ("root's password: ")
        if _root_password:
            _root_password += '\n'

    return _root_password

def exe_sudo (cmd, **kwargs):
    if os.getuid() != 0:
        root_password = get_root_password()
        kwargs['stdin'] = root_password
        cmd = "sudo -S " + cmd
    return exe (cmd, **kwargs)

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

def figure_initd_app_level (directory, app, not_found=99):
    files = [x.lower() for x in os.listdir(directory)]
    for filename in files:
        tmp = re.findall (r's(\d+)(.+)', filename)
        if not tmp: continue

        if tmp[0][1] == app:
            return tmp[0][0]

    return not_found

def make_path():
    return which("gmake") or which("make")


# Cherokee
#
def cherokee_download (tar_file):
    # Clean up
    rm (BUILD_DIR)
    rm (tar_file)
    mkdir (BUILD_DIR)

    # Download
    if download_snapshot:
        url = URL_SNAPSHOT_RELEASE
    else:
        url = URL_LATEST_RELEASE

    download (url, tar_file)


def cherokee_find_unpacked():
    for f in os.listdir (BUILD_DIR):
        fp = os.path.join (BUILD_DIR, f)
        tmp = re.findall (r'cherokee-(\d+\.\d+\.\d+)', f)
        if tmp and os.path.isdir (fp):
            return fp


def cherokee_unpack (latest_local):
    # Unpack
    ret = exe ("gzip -dc '%s' | tar xfv -" %(latest_local), cd=BUILD_DIR)
    if ret['retcode'] != 0:
        return None

    # Look for the src directory
    path = cherokee_find_unpacked()
    if not path:
        return

    # Works around clock issues
    touch = False
    for f in [os.path.join (path, x) for x in os.listdir (path)]:
        if os.stat(f)[stat.ST_MTIME] > time.time():
            touch = True
            break

    if touch:
        exe ("find '%s' -exec touch '{}' \;" %(path))

    return path


def cherokee_compile (src_dir):
    params="--prefix='%s'" %(prefix)

    # Look for gettext
    if not which ("msgfmt"):
        params += " --enable-nls=no"

    # Snaphost
    if download_snapshot:
        params += " --enable-beta"

    # Trace
    if devel_build:
        params += " --enable-trace"
        params += " CFLAGS='-ggdb3 -O0'"

    # Configure
    ret = exe ("./configure " + params, cd=src_dir)
    if ret['retcode'] != 0:
        return True

    # Build
    ret = exe (make_path(), cd=src_dir)
    if ret['retcode'] != 0:
        return True


def cherokee_install (src_dir):
    if os.access (prefix, os.W_OK):
        ret = exe ("%s install" %(make_path()), cd=src_dir)
    else:
        ret = exe_sudo ("%s install" %(make_path()), cd=src_dir)

    if ret['retcode'] != 0:
        return True


def cherokee_set_initd():
    print('')

    proceed = read_yes_no ("Do you want Cherokee to be started at boot time? [Y/n] ", True)
    if not proceed:
        return

    variables = globals()
    variables.update (locals())

    # MacOS X
    if sys.platform == 'darwin':
        tmp_fp   = os.path.join (BUILD_DIR, "launchd-cherokee.plist")
        plist_fp = os.path.join (prefix,    "launchd-cherokee.plist")

        # Write the plist file
        txt = LAUNCHD_PLIST %(variables)
        f = open (tmp_fp, 'w+')
        f.write (txt)
        f.close()

        # Permissions
        exe_sudo ("cp '%s' '%s'" %(tmp_fp, plist_fp))
        exe_sudo ("chown root  '%s'" %(plist_fp))
        exe_sudo ("chgrp admin '%s'" %(plist_fp))

        # Let launchd know about it
        exe_sudo ("launchctl unload -w '%s'" %(plist_fp))
        exe_sudo ("launchctl load -w '%s'" %(plist_fp))
        exe_sudo ("launchctl start org.cherokee.webserver")
        return

    # Solaris
    if sys.platform.startswith('sunos'):
        def smf_present():
            return (os.access ("/etc/svc/volatile/repository_door", os.R_OK) and
                    not os.path.isfile ("/etc/svc/volatile/repository_door"))

        variables['prefix_var'] = os.path.join (prefix, "var")

        tmp_fp = os.path.join (BUILD_DIR, "http-cherokee.xml")
        xml_fp = "/var/svc/manifest/network/http-cherokee.xml"

        # Write the plist file
        txt = SOLARIS_SVC %(variables)
        f = open (tmp_fp, 'w+')
        f.write (txt)
        f.close()

        # Permissions
        exe_sudo ("cp '%s' '%s'" %(tmp_fp, xml_fp))
        exe_sudo ("chown root '%s'" %(xml_fp))
        exe_sudo ("chgrp sys  '%s'" %(xml_fp))

        # Let launchd know about it
        if smf_present():
            exe_sudo ("/usr/sbin/svccfg import '%s'" %(xml_fp))
            exe_sudo ("/usr/sbin/svcadm enable svc:/network/http:cherokee")
        else:
            print ("INFO: Skipping SVC, SMF not present")
        return

    # BSD
    if 'bsd' in sys.platform.lower():
        rcd_fp = '/etc/rc.d/cherokee'

        # Preliminary clean up
        exe_sudo ("rm -f '%s'"%(rcd_fp))

        # Write the init.d file
        txt = BSD_INIT %(variables)
        f = open (rcd_fp, 'w+')
        f.write (txt)
        f.close()

        # Permissions
        exe_sudo ("chown root '%s'" %(rcd_fp))
        exe_sudo ("chmod 555 '%s'"  %(rcd_fp))

        return

    # Init.d
    if os.path.isdir ("/etc/init.d"):
        # Figure runlevel
        ret = exe ("runlevel")

        tmp = re.findall (r'(\d+)', ret['stdout'])
        if not tmp:
            print (red ("Could not figure the current runlevel. Skiping step."))
            return

        runlevel = tmp[0]

        # Figure rc<X>.d directory:
        # /etc/rc2.d
        # /etc/init.d/rc2.d
        rc_paths = ('/etc/rc%s.d'%(runlevel), '/etc/init.d/rc%s.d'%(runlevel))
        rc_dir   = None

        for d in rc_paths:
            if os.path.isdir (d):
                rc_dir = d
                break

        assert rc_dir, "Unknow init.d layout"

        # Build paths
        tmp_fp   = os.path.join (BUILD_DIR, "cherokee.initd")
        sh_fp    = os.path.join (prefix,    "cherokee.initd")
        initd_fp = "/etc/init.d/cherokee-opt"

        # Figure rc2.d file level
        level = 99
        for k in ('apache', 'apache2', 'httpd', 'lighttpd', 'nginx'):
            level = min (level, figure_initd_app_level (rc_dir, k))

        rcS_fp = os.path.join (rc_dir, "S%02dcherkee-opt"%(level-1))
        rcK_fp = os.path.join (rc_dir, "K%02dcherkee-opt"%(level-1))

        # Preliminary clean up
        exe_sudo ("rm -f '%s' '%s' '%s' '%s' '%s'" %(tmp_fp, sh_fp, initd_fp, rcS_fp, rcK_fp))

        # Write the init.d file
        txt = INITD_SH %(variables)
        f = open (tmp_fp, 'w+')
        f.write (txt)
        f.close()

        # Permissions
        exe_sudo ("cp '%s' '%s'" %(tmp_fp, sh_fp))
        exe_sudo ("chown root '%s'" %(sh_fp))
        exe_sudo ("chmod 755 '%s'"  %(sh_fp))

        # Add it
        exe_sudo ("ln -s '%s' '%s'" %(sh_fp, initd_fp))  # /etc/init.d/cherokee   -> /opt/..
        exe_sudo ("ln -s '%s' '%s'" %(initd_fp, rcS_fp)) # /etc/rc2.d/S99cherokee -> /etc/init.d/..
        exe_sudo ("ln -s '%s' '%s'" %(initd_fp, rcK_fp)) # /etc/rc2.d/K99cherokee -> /etc/init.d/..


def cherokee_report():
    cherokee_fp = os.path.join (prefix, "sbin", "cherokee")

    print (blue ("Technical details:"))
    exe ("%s -i" %(cherokee_fp))

    print (blue ("How to:"))
    print (" - Launch manually the server:      %s/sbin/cherokee -d" %(prefix))
    print (" - Launch the administration GUI:   %s/bin/cherokee-admin-launcher" %(prefix))


# Main
#
def main():
    tar_file = os.path.join (BUILD_DIR, "cherokee-latest.tar.gz")

    if start_at <= PHASE_DOWNLOAD:
        cherokee_download (tar_file)

    if start_at <= PHASE_UNPACK:
        src_dir = cherokee_unpack (tar_file)
        if not src_dir: return
    else:
        src_dir = cherokee_find_unpacked()
        if not src_dir: return

    if start_at <= PHASE_COMPILE:
        error = cherokee_compile (src_dir)
        if error: return

    if start_at <= PHASE_INSTALL:
        error = cherokee_install (src_dir)
        if error: return

    if start_at <= PHASE_INITD:
        cherokee_set_initd()

    if start_at <= PHASE_REPORT:
        cherokee_report ()


def check_prerequisites():
    # Check for a C compiler
    if not which("gcc") and not which("cc"):
        if sys.platform == 'sunos5':
            cont = read_yes_no ("SUNWgcc must be installed. Proceed? [Y/n] ", True)
            if not cont:
                raise SystemExit
            exe ("pkg install SUNWgcc")
        else:
            FATAL_error ("A C compiler is required")

    # Check for Python
    if not which("env"):
        FATAL_error ("'env' is required")

    ret = exe ("env python -V")
    if ret['retcode'] != 0:
        FATAL_error ("Python is not in the path")

    # Check for make
    if not make_path():
        FATAL_error ("'make' or 'gmake' is required for the compilation")


def process_parameters():
    global start_at
    global download_snapshot
    global devel_build
    global prefix

    if '--help' in sys.argv:
        print ("Cherokee's assisted deployment script:")
        print ("  USAGE: python install.py [params]")
        print ("")
        print ("  --snapshot         Compile latest development snapshot")
        print ("  --devel            snapshot w/ debug under cherokee-dev")
        print ("")
        print ("  Development:")
        print ("    --from-unpack    Start at the 'unpack' phase")
        print ("    --from-compile   Start at the 'compilation' phase")
        print ("    --from-install   Start at the 'install' phase")
        print ("    --from-initd     Start at the 'initd' phase")
        print ("    --from-report    Start at the 'report' phase")
        print ("")
        print ("Report bugs to: http://bugs.cherokee-project.com/")
        raise SystemExit

    # Development
    if '--snapshot' in sys.argv:
        download_snapshot = True

    if '--devel' in sys.argv:
        devel_build       = True
        download_snapshot = True
        prefix            = PREFIX_DEVEL

    # Script development
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
