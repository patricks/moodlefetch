#!/usr/bin/env python

#########################################################################
# This program is free software: you can redistribute it and/or modify  #
# it under the terms of the GNU General Public License as published by  #
# the Free Software Foundation, either version 3 of the License, or     #
# (at your option) any later version.                                   #
#                                                                       #
# This program is distributed in the hope that it will be useful,       #
# but WITHOUT ANY WARRANTY; without even the implied warranty of        #
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         #
# GNU General Public License for more details.                          #
#                                                                       #
# You should have received a copy of the GNU General Public License     #
# along with this program.  If not, see <http://www.gnu.org/licenses/>. #
#########################################################################

__version__ = "0.1"

import re
import sys, os, ConfigParser
import urllib
import urllib2
import getpass
import cookielib

#
# DEFAULT CONFIGURATION PATH GOES HERE
DEFAULTCONFIG = "~/.moodlefetch.cfg"

#since the default urllib2 HTTPRedirectHandler leaves us no option to disable auto-redirects
#we have to implement our own Handler in order to get the final urls and original filenames from moodle
class MyHTTPRedirectHandler(urllib2.HTTPRedirectHandler):
  def http_error_303(self, req, fp, code, msg, headers):
    return headers.getheaders('location')[0]
  http_error_301 = http_error_302 = http_error_307 = http_error_303

cj = cookielib.CookieJar()
opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj))
openerNo303Handler = urllib2.build_opener(MyHTTPRedirectHandler, urllib2.HTTPCookieProcessor(cj))

def usage():
  print('usage: %s [configfile]' % sys.argv[0])

config = ConfigParser.RawConfigParser()
if len(sys.argv) == 2:
  config.read(sys.argv[1])
else:
  if os.path.isfile(os.path.expanduser(DEFAULTCONFIG)):
    config.read(os.path.expanduser(DEFAULTCONFIG))
  else:
    usage()
    sys.exit()

if config.get('general', 'output') == "notify":
  import pynotify
if config.get('general', 'output') == "growl":
  import gntp.notifier
if config.get('general', 'keyring') == "true":
  import keyring

def moodle_login(username, password):
  uri = 'https://elearning.fh-hagenberg.at/login/index.php'
  req = urllib2.Request(uri)
  f = opener.open(req)
  data = f.read()
  formFields = (
              (r'username', username),
              (r'password', password)
              )
  encodedFields = urllib.urlencode(formFields)
  req = urllib2.Request(uri, encodedFields)
  f = opener.open(req)
  if f:
    debug('login successful')

def moodle_getcourses(semester):
  uri = 'https://elearning.fh-hagenberg.at/?role=0&cat=1&stg=all&sem=&csem=0'
  req = urllib2.Request(uri)
  f = opener.open(req)
  data = f.read()
  data = re.findall(r'(?<=\<option\ value=").*>'+semester+'<\/option>', data)
  semesterid = re.split('"', data[0])
  uri = 'https://elearning.fh-hagenberg.at/?role=0&cat=1&stg=all&sem='+semesterid[0]+'&csem=0'
  req = urllib2.Request(uri)
  f = opener.open(req)
  data = f.read()
  matches = re.findall(r'(?<=course\/view\.php\?id\=).*</a>', data)
  for match in matches:
    split = re.split('\.', re.sub(', ', '.', re.sub('">', '.', re.sub('</a>', '', match))))
    courseid = split[0]
    coursename = split[3]+"-"+split[5]
    try:
      coursename = config.get('courses', coursename)
    except:
      coursename = split[3]+"-"+split[5]
    debug("looking for new files in: "+coursename)
    moodle_getfiles(courseid, coursename, config.get('general', 'dstdir'))

def moodle_getfiles(courseid, coursename, dstdir):
  path = dstdir+'/'+coursename
  if not os.path.exists(path):
    debug('creating directory '+path)
    os.makedirs(path)
  localFiles = getLocalFiles(path)
  uri = 'https://elearning.fh-hagenberg.at/course/view.php?id='+courseid
  req = urllib2.Request(uri)
  f = opener.open(req)
  data = f.read()
  matches = re.findall(r'(?<=href=").*pdf\.gif" class="activityicon" alt="" \/> <span>.*<span', data)
  for match in matches:
    fileid = re.findall(r'(?<=id=)[0-9]+', match)
    files = re.findall(r'(?<=<span>).*<', match)
    # filename['htmlsrc'] and filename['orig'] added to provide compatibility with archives generated before 2012-03-30
    filename = {'htmlsrc':  '',
                'orig':     ''}
    filename['htmlsrc'] = path+'/'+re.sub('/', '_', re.sub('\<', '.pdf', re.sub(' ', '_', files[0])))
    uri = 'https://elearning.fh-hagenberg.at/mod/resource/view.php?inpopup=true&id='+fileid[0]
    uri = openerNo303Handler.open(uri)
    srcurl, filename['orig'] = uri.rsplit('/', 1)
    try:
      filename['orig'], args = filename['orig'].rsplit('?', 1)
    except:
      filename['orig'] = filename['orig']
    
    filename['orig'] = path+"/"+filename['orig']
    #take care of older archives
    if filename['htmlsrc'] in localFiles:
      if filename['htmlsrc'] != filename['orig']:
        debug("moved "+filename['htmlsrc']+" "+path+"/"+filename['orig'])
        os.rename(filename['htmlsrc'], filename['orig'])
    if not config.get('general', 'forcedownload') == "true":
      if filename['orig'] not in localFiles:
        #also for older archives...
        if filename['htmlsrc'] not in localFiles:
          moodle_fedch(uri, filename['orig'])
    else:
        moodle_fedch(uri, filename['orig'])

def moodle_fedch(uri, filename):
  req = urllib2.Request(uri)
  f = opener.open(req)
  debug('writing: '+filename)
  localFile = open(filename, 'w')
  localFile.write(f.read())
  localFile.close()
  

def getLocalFiles(dstdir):
  localFiles = list()
  for top, dirs, files in os.walk(dstdir):
    for nm in files:       
      localFiles.append(os.path.join(top, nm))
  return localFiles

def moodle_logout():
  uri = "https://elearning.fh-hagenberg.at/index.php"
  req = urllib2.Request(uri)
  f = opener.open(req)
  data = f.read()
  data = re.findall(r'(?<=logout\.php\?sesskey=)[^"]+', data)
  sessionkey = data[0]
  uri = 'http://elearning.fh-hagenberg.at/login/logout.php?sesskey='+sessionkey
  req = urllib2.Request(uri)
  f = opener.open(req)
  data = f.read()
  if re.search('Sie sind nicht angemeldet', data):
    debug('logout successful')
  else:
    debug('logout failed')

def debug(msg):
  if config.get('general', 'output') == "stdout":
    print msg
  if config.get('general', 'output') == "notify":
    n = pynotify.Notification("moodlefetch", msg)
    n.show()
  if config.get('general', 'output') == "growl":
    gntp.notifier.mini(msg)

if config.get('general', 'output') == "notify":
  pynotify.init("moodlefedch")

if config.get('general', 'keyring') == "true":
  try:
    password = keyring.get_password("moodlefetch", config.get('moodle', 'username'))
    if password == None:
      keyring.set_password("moodlefetch", config.get('moodle', 'username'), getpass.getpass())
      password = keyring.get_password("moodlefetch", config.get('moodle', 'username'))
  except:
    debug("getting password from keyring failed...")
    sys.exit(1)
else:
  if not config.get('moodle', 'password'):
    password = getpass.getpass()
  else:
    password = config.get('moodle', 'password')

moodle_login(config.get('moodle', 'username'), password)
moodle_getcourses(config.get('moodle', 'semester'))
moodle_logout()
