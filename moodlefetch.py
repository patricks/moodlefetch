#!/usr/bin/env python
# -*- coding: utf-8 -*-
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
__program__ = 'moodlefetch'
__url__ = 'http://github.com/mnlhfr/moodlefetch'
__author__ = 'Manuel Hofer <S1110239019@students.fh-hagenberg.at>'

# @todo: config parsing
username = "S1110239019"
password = ""

class MyHTTPRedirectHandler(urllib2.HTTPRedirectHandler):
# since the default urllib2 HTTPRedirectHandler leaves us no option to disable auto-redirects
# we have to implement our own Handler in order to get the final urls and original filenames from moodle
  def http_error_303(self, req, fp, code, msg, headers):
    return headers.getheaders('location')[0]
  http_error_301 = http_error_302 = http_error_307 = http_error_303

class MoodlefetchGetFilenames(threading.Thread):
# This class is called by the Moodlefetch class in order to populate
# all previously obtained Course Objects with File Objects
    def __init__(self, parent, course):
    # @param parent: the calling Moodlefetch Object itself
    # @param course: the Course Object we are operating on 
        threading.Thread.__init__(self)
        self.parent = parent
        self.course = course
    def run(self):
        # get the course overview page and match all links to pdf files in it
        uri = self.parent.baseuri+'/course/view.php?id='+self.course.id
        req = urllib2.Request(uri)
        f = self.parent.opener.open(req)
        data = f.read()
        matches = re.findall(r'(?<=href=").*pdf\.gif" class="activityicon" alt="" \/> <span>.*<span', data)
        for match in matches:
        # creating a File object for every file, populating it, and adding it to the files_available array
        # of the Course object.
            file = File()
            file.id = re.findall(r'(?<=id=)[0-9]+', match)[0]
            file.type = 'pdf' #TODO / just for now
            uri = self.parent.baseuri+'/mod/resource/view.php?inpopup=true&id='+file.id
            # we need to use our No303Handler class here to not get directly redirected to
            # be able to read the correct filenames by not following the HTTP303 redirect 
            f = self.parent.openerNo303Handler.open(uri)
            srcurl, file.name = f.rsplit('/', 1)
            self.course.addFileAvailable(file)
            logger.debug("course.files_available: added file "+file.name+" with id: "+str(file.id))

class MoodlefetchDownloadFile(threading.Thread):
# This class is called by the Moodlefetch class in order to download ALL the files
# in a specific Course objects files_to_get array.
    def __init__(self, parent, course, file, bytes_done, bytes_total):
    # @param parent: the calling Moodlefetch object itself
    # @param course: the specific Course object to download files for
    # @param file: : the File object to download
    # @param bytes_done: a piece of shared memory to keep track of the number of already downloaded bytes
    # @param bytes_total: - number of bytes in total
        threading.Thread.__init__(self)
        self.parent = parent
        self.course = course
        self.file = file
        self.bytes_done = bytes_done
        self.bytes_total = bytes_total
    def run(self):
        # create directorys if not existent
        if not os.path.exists(self.course.path):
            try:
                os.makedirs(self.course.path)
                logger.info('created directory '+self.course.path)
            except:
                logger.error('problem creating directory '+self.course.path)
                return
        # download the file
        uri = self.parent.baseuri+'/mod/resource/view.php?inpopup=true&id='+str(self.file.id)
        req = urllib2.Request(uri)
        f = self.parent.opener.open(req)
        # get content-length header and add the value to bytes_total
        logger.debug("received content-length: "+str(f.headers.get("content-length")))
        self.bytes_total.value += int(f.headers.get("content-length")) 
        # try to save the received data stream to disk
        try:
            localFile = open(self.course.path+self.file.name, 'w')
            localFile.write(f.read())
            localFile.close()
            logger.info('file saved: '+self.course.path+self.file.name)
            # update bytes_done
            self.bytes_done.value += int(f.headers.get("content-length")) 
        except:
            logger.error("failed to write "+self.course.path+self.file.name)

class Moodlefetch():
    cj = cookielib.CookieJar()
    opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj))
    openerNo303Handler = urllib2.build_opener(MyHTTPRedirectHandler, urllib2.HTTPCookieProcessor(cj))
    semesterid = 0 # getSemesterId will change this
    courses = [] # array of Course objects populated by getCourses
    local_files = [] #used to store File objects of files already available in the local directory
    baseuri = 'https://elearning.fh-hagenberg.at'
    dir = "/tmp/moodlefetch/" # files downloaded to this directory
    
    def login(self, username, password):
    # execute login and exit on failure
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
        # check if we are really logged in
        # since moodle hands out a sessioncookie even if the login failed
        # we cant just check if moodle put us a delicious cookie in our cookiejar.
        # therefore we check for the keyword "logout" to verify. 
        uri = self.baseuri
        req = urllib2.Request(uri)
        f = self.opener.open(req).read()
        if re.search('logout', f) != None:
            logger.info("logged in")
        else:
            logger.error("login failed. exiting")
            sys.exit(-1)
            
    def getSemesterId(self, semester):
    # @param semester: string like "WS11/12", "SS12" like presented in the dropdown menue at the moodle start page
    # stores the corresponding semesterID in self.semesterId
        uri = self.baseuri+'/?role=0&cat=1&stg=all&sem=&csem=0'
        req = urllib2.Request(uri)
        f = self.opener.open(req)
        response = f.read()
        response = re.findall(r'(?<=\<option\ value=").*>'+semester+'<\/option>', response)
        self.semesterid = re.split('"', response[0])[0]
        
    def getCourses(self):
    # populating self.courses[] with Course objects
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
    # populates self.local_files with Course objects
        for top, dirs, files in os.walk(self.dir):
            for nm in files:
                self.local_files.append(os.path.join(top, nm))
                
    def sync(self):
        # get information about local files and compare them to available files
        self.getLocalFiles()
        # create two integers in shared memory to be updated by the download threads
        bytes_done = Value('d', 0)
        bytes_total = Value('d', 0)
        # loop through each courses File objects and check whether files already exist in our local directory
        for course in self.courses:
            for file in course.files_available:
                if course.path+file.name not in self.local_files:
                    course.addFileToGet(file)
                    logger.debug("course.files_to_get: added file "+file.name+" with id: "+str(file.id))
            #get files that are not available in our local directory
            for file in course.files_to_get:
                while True:
                    #limit the maximum number of parallel downloads
                    if(threading.activeCount() < 11):
                        thread = MoodlefetchDownloadFile(self, course, file, bytes_done, bytes_total)
                        thread.start()
                        logger.debug('started download thread for file: '+file.name)
                        break
                    else:
                        time.sleep(0.1)
                    logger.info(str(bytes_done.value)+"/"+str(bytes_total.value))
                    print "\r"+str(bytes_done.value)+"/"+str(bytes_total.value)
        # wait for all threads to finish up downloading
        while (threading.activeCount() > 1):
            pass
        
    def __init__(self, username, password):
        logger.debug("starting initialization of moodlefetch class")
        self.login(username, password)
        self.getSemesterId('SS12')
        self.getCourses()
        logger.debug("finished initialization of moodlefetch class")
            
class Course:
# entity class describing a course in moodle and providing basic functionality to add File objects
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
# entity class for files
# u dont' say?
    def __init__(self):
        self.id = 0
        self.type = "" #for future use
        self.name = ""

if __name__ == "__main__":
    # Setup basic logging
    logger = logging.getLogger('moodlefetch')
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler('/dev/stdout')
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)
    # start the magic
    moodle = Moodlefetch(username, password)
    for course in moodle.courses:
        thread = MoodlefetchGetFilenames(moodle, course)
        thread.start()
    while (threading.activeCount() > 1):
        pass
    moodle.sync()