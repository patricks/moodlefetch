import re
import sys, os, ConfigParser
import urllib
import urllib2
import getpass
import cookielib
import pynotify

cj = cookielib.CookieJar()
opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj))

def usage():
  print('usage: %s [configfile]' % sys.argv[0])

config = ConfigParser.RawConfigParser()
if len(sys.argv) == 2:
  config.read(sys.argv[1])
else:
  usage()
  sys.exit()

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
    filename = path+'/'+re.sub('/', '_', re.sub('\<', '.pdf', re.sub(' ', '_', files[0])))
    uri = 'https://elearning.fh-hagenberg.at/mod/resource/view.php?inpopup=true&id='+fileid[0]
    if not config.get('general', 'forcedownload') == "true":
      if filename not in localFiles:
        moodle_fedch(uri, filename)
    else:
        moodle_fedch(uri, filename)

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
  if config.get('general', 'output') == "console":
    print msg
  if config.get('general', 'output') == "notify":
    n = pynotify.Notification("moodlefetch", msg)
    n.show()

if not config.get('moodle', 'password'):
  password = getpass.getpass()
else:
  password = config.get('moodle', 'password')

if config.get('general', 'output') == "notify":
  pynotify.init("moodlefedch")

moodle_login(config.get('moodle', 'username'), password)
moodle_getcourses(config.get('moodle', 'semester'))
moodle_logout()
