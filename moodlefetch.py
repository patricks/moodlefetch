import re
import sys, os, ConfigParser
import urllib
import urllib2
import getpass
import cookielib
import new
import threading, time
from multiprocessing import Value
import logging

# Setup basic logging
logger = logging.getLogger('moodlefetch')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('/dev/null')
fh.setLevel(logging.DEBUG)
logger.addHandler(fh)

class MyHTTPRedirectHandler(urllib2.HTTPRedirectHandler):
  def http_error_303(self, req, fp, code, msg, headers):
    return headers.getheaders('location')[0]
  http_error_301 = http_error_302 = http_error_307 = http_error_303

class MoodlefetchGetFilenames(threading.Thread):    
    def __init__(self, parent, course):
        threading.Thread.__init__(self)
        self.parent = parent
        self.course = course
    def run(self):
        uri = self.parent.baseuri+'/course/view.php?id='+self.course.id
        req = urllib2.Request(uri)
        f = self.parent.opener.open(req)
        data = f.read()
        matches = re.findall(r'(?<=href=").*pdf\.gif" class="activityicon" alt="" \/> <span>.*<span', data)
        for match in matches:
            file = File()
            file.id = re.findall(r'(?<=id=)[0-9]+', match)[0]
            file.type = 'pdf' #TODO / just for now
            uri = self.parent.baseuri+'/mod/resource/view.php?inpopup=true&id='+file.id
            f = self.parent.openerNo303Handler.open(uri)
            srcurl, file.name = f.rsplit('/', 1)
            self.course.addFileAvailable(file)
            logger.debug("course.files_available: added file "+file.name+" with id: "+str(file.id))

class MoodlefetchDownloadFile(threading.Thread):    
    def __init__(self, parent, course, file, bytes_done, bytes_total):
        threading.Thread.__init__(self)
        self.parent = parent
        self.course = course
        self.file = file
        self.bytes_done = bytes_done
        self.bytes_total = bytes_total
    def run(self):
        if not os.path.exists(self.course.path):
            try:
                os.makedirs(self.course.path)
                logger.info('created directory '+self.course.path)
            except:
                logger.error('problem creating directory '+self.course.path)
        uri = self.parent.baseuri+'/mod/resource/view.php?inpopup=true&id='+str(self.file.id)
        req = urllib2.Request(uri)
        f = self.parent.opener.open(req)
        logger.debug("received content-length: "+str(f.headers.get("content-length")))
        self.bytes_total.value += int(f.headers.get("content-length")) 
        try:
            localFile = open(self.course.path+self.file.name, 'w')
            localFile.write(f.read())
            localFile.close()
            logger.info('file saved: '+self.course.path+self.file.name)
            self.bytes_done.value += int(f.headers.get("content-length")) 
        except:
            logger.error("failed to write "+self.course.path+self.file.name)

class Moodlefetch():
    cj = cookielib.CookieJar()
    opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj))
    openerNo303Handler = urllib2.build_opener(MyHTTPRedirectHandler, urllib2.HTTPCookieProcessor(cj))
    semesterid = 0
    courses = []
    local_files = []
    baseuri = 'https://elearning.fh-hagenberg.at'
    dir = "/tmp/moodlefetch/"
    
    def login(self, username, password):
        uri = self.baseuri+'/login/index.php'
        req = urllib2.Request(uri)
        f = self.opener.open(req)
        data = f.read()
        formFields = (
              (r'username', username),
              (r'password', password),
              )
        encodedFields = urllib.urlencode(formFields)
        req = urllib2.Request(uri, encodedFields)
        self.opener.open(req)
        #TODO checking on cj doesnt help anything
        if self.cj:
            logger.info("logged in")
        else:
            logger.error("login failed. exiting")
            
    def getSemesterId(self, semester):
        uri = self.baseuri+'/?role=0&cat=1&stg=all&sem=&csem=0'
        req = urllib2.Request(uri)
        f = self.opener.open(req)
        response = f.read()
        response = re.findall(r'(?<=\<option\ value=").*>'+semester+'<\/option>', response)
        self.semesterid = re.split('"', response[0])[0]
        
    def getCourses(self):
        uri = self.baseuri+'/?role=0&cat=1&stg=all&sem='+self.semesterid+'&csem=0'
        req = urllib2.Request(uri)
        f = self.opener.open(req)
        data = f.read()
        matches = re.findall(r'(?<=course\/view\.php\?id\=).*</a>', data)
        for match in matches:
            course = Course()
            split = re.split('\.', re.sub(', ', '.', re.sub('">', '.', re.sub('</a>', '', match))))
            course.id = split[0]
            course.name = split[3]+"-"+split[5]
            try:
                course.name = config.get('courses', Course.name)
            except:
                course.name = split[3]+"-"+split[5]
            course.path = self.dir+course.name+'/'
            self.courses.append(course)
            
    def getLocalFiles(self):
        for top, dirs, files in os.walk(self.dir):
            for nm in files:
                self.local_files.append(os.path.join(top, nm))
                
    def sync(self):
        #get information about local files and compare them to available files
        self.getLocalFiles()
        bytes_done = Value('d', 0)
        bytes_total = Value('d', 0)
        for course in self.courses:
            for file in course.files_available:
                if course.path+file.name not in self.local_files:
                    course.addFileToGet(file)
                    logger.debug("course.files_to_get: added file "+file.name+" with id: "+str(file.id))
            #get files that are not available in our local directory
            for file in course.files_to_get:
                while True:
                    #we only want a maximum of 5 parallel downloads
                    if(threading.activeCount() < 6):
                        thread = MoodlefetchDownloadFile(self, course, file, bytes_done, bytes_total)
                        thread.start()
                        logger.debug('started download thread for file: '+file.name)
                        break
                    else:
                        time.sleep(0.1)
                    logger.info(str(bytes_done.value)+"/"+str(bytes_total.value))
                    print "\r"+str(bytes_done.value)+"/"+str(bytes_total.value)
        while (threading.activeCount() > 1):
            pass
        
    def __init__(self, username, password):
        self.login(username, password)
        self.getSemesterId('SS12')
        self.getCourses()
        for course in self.courses:
            thread = MoodlefetchGetFilenames(self, course)
            thread.start()
        while (threading.activeCount() > 1):
            pass
        self.sync()
            
class Course:
    def __init__(self):
        self.id = 0
        self.name = ""
        self.path = ""
        self.files_available = []
        self.files_to_get = []
        
    def addFileAvailable(self, file):
        self.files_available.append(file)
        
    def addFileToGet(self, file):
        self.files_to_get.append(file)

class File:
    def __init__(self):
        self.id = 0
        self.type = "" #for future use
        self.name = ""

#no config parsing yet
username = "S1110239019"
password=""
moodle = Moodlefetch(username, password)
