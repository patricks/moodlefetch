#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import sys, os, signal
import ConfigParser
import urllib
import urllib2
import getpass
import cookielib
import threading, time
from multiprocessing import Value
import logging
from optparse import OptionParser, OptionGroup

__program__ = 'moodlefetch'
__url__     = 'http://github.com/mnlhfr/moodlefetch'
__author__  = 'Manuel Hofer <S1110239019@students.fh-hagenberg.at>'

# Setup signal handling to avoid Exceptions when CTRL+C is pressed
def signal_handler(signal, frame):
        print 'You pressed CTRL+C, exiting gracefully'
        del moodle
        sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)

# Setup basic logging
logger = logging.getLogger('moodlefetch')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('/dev/stdout')
fh.setLevel(logging.DEBUG)
logger.addHandler(fh)

# processing configuration
# initialize with default values
config = {'username': '',
          'password': '',
          'auth_type': 'password',
          'directory': '.',
          'semester': 'SS12',
          }

# option parsing
parser = OptionParser()
parser_auth = OptionGroup(parser, "Authentification:")
parser_auth.add_option("-u", "--username", action="store", type="string", dest="username")
parser_auth.add_option("-p", "--password", action="store", type="string", dest="password")
parser_auth.add_option("-a", "--auth_type", action="store", dest="auth_type", help="choose between 'password' and 'keyring'")
parser.add_option_group(parser_auth)    
parser_configuration = OptionGroup(parser, "Configuration:")
parser_configuration.add_option("-c", "--config", action="store", type="string", dest="config", help="configuration file")
parser_configuration.add_option("-d", "--directory", action="store", type="string", dest="directory", help="directory for moodle file sync")
parser_configuration.add_option("-s", "--semester", action="store", type="string", dest="semester", help="a string like 'SS12' or 'WS11/12'")
parser.add_option_group(parser_configuration)
parser_actions = OptionGroup(parser, "Actions:")
parser_actions.add_option("--deadlines", action="store_true", dest="getDeadlines")
parser_actions.add_option("--grades", action="store_true", dest="getGrades")
parser_actions.add_option("--sync", action="store_true", dest="sync")
parser.add_option_group(parser_actions)
options, args = parser.parse_args()

# configuration parsing
config_parser = ConfigParser.RawConfigParser()
default_config = os.path.expanduser('~/.moodlefetch')
config_path = default_config
if options.config:
    config_path = options.config
elif os.path.isfile(default_config):
    print "defaulting to "+default_config
    config_path = default_config
if config_parser.read(config_path):
    config = {'username': config_parser.get('moodle', 'username'),
              'password': config_parser.get('moodle', 'password'),
              'auth_type':  config_parser.get('general', 'auth_type'),
              'directory': config_parser.get('general', 'directory'),
              'semester': config_parser.get('moodle', 'semester'),
              }
    
# override config settings with command line args
if options.username != None:
    config['username'] = options.username
if options.password != None:
    config['password'] = options.password
if options.auth_type != None:
    config['auth_type'] = options.auth_type
if options.directory != None:
    config['directory'] = options.directory
if options.semester != None:
    config['semester'] = options.semester

# check auth_type and get a password
if config['auth_type'] == "keyring":
    try:
        import keyring
    except:
        logger.error("unable to import keyring")
    try:
        config['password'] = keyring.get_password("moodlefetch", config['username'])
        if config['password'] == None:
            keyring.set_password("moodlefetch", config['username'], getpass.getpass())
            config['password'] = keyring.get_password("moodlefetch", config['username'])
    except:
        logger.error("getting password from keyring failed...")
        sys.exit(10)
elif config['auth_type'] == 'password':
    if config['password'] == "":
        config['password'] = getpass.getpass()

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
            f = File()
            f.id = re.findall(r'(?<=id=)[0-9]+', match)[0]
            f.type = 'pdf' #TODO / just for now
            uri = self.parent.baseuri+'/mod/resource/view.php?inpopup=true&id='+f.id
            # we need to use our No303Handler class here to not get directly redirected to
            # be able to read the correct filenames by not following the HTTP303 redirect 
            fetcher = self.parent.openerNo303Handler.open(uri)
            srcurl, f.name = fetcher.rsplit('/', 1)
            f.name = str(f.name).replace('?forcedownload=1', '')
            self.course.addFileAvailable(f)
            logger.debug("course.files_available: added file "+f.name+" with id: "+str(f.id))

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

class MoodlefetchGetGrades(threading.Thread):
# @todo: 
    def __init__(self, parent, course):
        threading.Thread.__init__(self)
        self.parent = parent
        self.course = course
    def run(self):
        uri = self.parent.baseuri+'/grade/report/user/index.php?id='+self.course.id
        req = urllib2.Request(uri)
        f = self.parent.opener.open(req)
        grade_ids = re.findall(r'(?<=grade\.php\?id\=)[^"]+', f.read())
        for grade_id in grade_ids:
            uri = self.parent.baseuri+'/mod/assignment/view.php?id='+grade_id
            req = urllib2.Request(uri)
            f = self.parent.opener.open(req)
            response = f.read()
            grade = Grade()
            grade.id = grade_id
            try:
                grade.name = re.findall(r'(?<=Aufgabe:\ )[^"]+', response)[0]
                points = re.findall(r'(?<=Bewertung:\ )[^<]+', response)[0]
                grade.points_has = re.sub(' ', '', re.sub(',', '.', re.findall(r'(?<=)[^/]+', points)[0]))
                grade.points_total = re.sub(' ', '', re.sub(',', '.', re.findall(r'(?<=/).*', points)[0]))
                self.course.addGrade(grade)
            except:
                logger.debug(self.course.name+": no grades available")
                pass

class MoodlefetchGetAssignments(threading.Thread):
    def __init__(self, parent, course):
        threading.Thread.__init__(self)
        self.parent = parent
        self.course = course
    def run(self):
        uri = self.parent.baseuri+'/calendar/view.php?view=upcoming&course='+self.course.id
        req = urllib2.Request(uri)
        f = self.parent.opener.open(req)
        response = f.read()
        assignment_ids = re.findall(r'(?<=\/mod\/assignment\/view\.php\?id\=)[^"]+', response)
        for assignment_id in assignment_ids:
            uri = self.parent.baseuri+'/mod/assignment/view.php?id='+assignment_id
            req = urllib2.Request(uri)
            f = self.parent.opener.open(req)
            response = f.read()
            assignment = Assignment()
            assignment.id = assignment_id
            assignment.duedate = re.findall(r'(?<=Abgabetermin:<\/td>    <td class="c1">)[^<]+', response)[0]
            assignment.name = re.findall(r'(?<=Aufgabe:\ )[^"]+', response)[0]
            self.course.addAssignment(assignment)


class Moodlefetch():
    cj = cookielib.CookieJar()
    opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj))
    openerNo303Handler = urllib2.build_opener(MyHTTPRedirectHandler, urllib2.HTTPCookieProcessor(cj))
    semesterid = None # getSemesterId will change this
    courses = [] # array of Course objects populated by getCourses
    local_files = [] #used to store File objects of files already available in the local directory
    baseuri = 'https://elearning.fh-hagenberg.at'
    # @todo: change dir to something else
    dir = None # files downloaded to this directory
        
    def login(self, username, password):
    # execute login and exit on failure
        uri = self.baseuri+'/login/index.php'
        req = urllib2.Request(uri)
        f = self.opener.open(req)
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
        response = re.findall(r'[0-9](?=" >'+semester+')', response)
        self.semesterid = re.split('"', response[0])[0]
        
    def getCourses(self):
    # populating self.courses[] with Course objects
        uri = self.baseuri+'/?role=0&cat=1&stg=all&sem='+self.semesterid+'&csem=0'
        req = urllib2.Request(uri)
        f = self.opener.open(req)
        data = f.read()
        matches = re.findall(r'(?<=course\/view\.php\?id\=).*</a>', data)
        for match in matches:
            split = re.split('\.', re.sub(', ', '.', re.sub('">', '.', re.sub('</a>', '', match))))
            if split[0] not in self.courses:
                course = Course()
                course.id = split[0]
                course.name = split[3]+"-"+split[5]
                try:
                    course.name = config.get('courses', Course.name)
                except:
                    course.name = split[3]+"-"+split[5]
                course.path = self.dir+course.name+'/'
                self.courses.append(course)
                logger.debug("added course "+course.name)
            
    def getLocalFiles(self):
    # populates self.local_files with Course objects
    # @todo:
        for top, dirs, files in os.walk(self.dir):
            for nm in files:
                self.local_files.append(os.path.join(top, nm))
                
    def sync(self):
        logger.debug("getting filenames and corresponding urls")
        for course in self.courses:
            thread = MoodlefetchGetFilenames(self, course)
            thread.start()
        while (threading.activeCount() > 1):
            pass
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
        print "sync done."
        
    def getDeadlines(self):
        for course in self.courses:
            thread = MoodlefetchGetAssignments(self, course)
            thread.start()
            logger.debug("started thread: MoodlefetchGetAssignments")
        logger.debug("waiting for threads to finish")
        while (threading.active_count() > 1):
            pass
        for course in self.courses:
            if course.assignments:
                print "=== "+course.name+" ==="
            for assignment in course.assignments:
                print "  * "+assignment.name
                print "    - "+assignment.duedate
            if course.assignments:
                print ""
            
        
    def getGrades(self):
    #populates a course with assignment grades
        for course in self.courses:
            #start one thread for every course
            thread = MoodlefetchGetGrades(self, course)
            thread.start()
            logger.debug("started thread: MoodlefetchGetGrades")
        logger.debug("waiting for threads to finish")
        while (threading.activeCount() > 1):
            pass
        for course in self.courses:
            if course.grades:
                print "=== "+course.name+" ==="
            for grade in course.grades:
                print "  * "+grade.name
                print "    - URL: "+self.baseuri+"/mod/assignment/view.php?id="+grade.id
                print "    - "+grade.points_has+" / "+grade.points_total
            if course.grades:
                print " "

    def __init__(self, username, password, semester, directory):
        logger.debug("starting initialization of moodlefetch class")
        if os.path.isdir(directory):
            self.dir = os.path.normpath(directory)+os.sep
        else:
            logger.error("No such directory!")
        self.login(username, password)
        self.getSemesterId(semester)
        if self.semesterid == 0:
            logger.error("failed to get semesterId, exiting")
        self.getCourses()
        logger.debug("finished initialization of moodlefetch class")
            
class Course:
# entity class describing a course in moodle and providing basic functionality to add File objects
    def __init__(self):
        self.id = None
        self.name = None
        self.path = None
        self.files_available = []
        self.files_to_get = []
        self.grades = []
        self.assignments = []
        
    def addFileAvailable(self, file):
        self.files_available.append(file)
        
    def addFileToGet(self, file):
        self.files_to_get.append(file)
        
    def addGrade(self, grade):
        self.grades.append(grade)

    def addAssignment(self, assignment):
        self.assignments.append(assignment)

class File:
# entity class for files
# u dont' say?
    def __init__(self):
        self.id = None
        self.type = None #for future use
        self.name = None

class Assignment:
# entity class for assignments
    def __init__(self):
        self.id = None
        self.name = None
        self.duedate = None

class Grade:
# class to reflect grades on assignments
    def __init__(self):
        self.id = None
        self.name = None
        self.points_has = None
        self.points_total = None
    
if __name__ == "__main__":
    try:
        moodle = Moodlefetch(config['username'], config['password'], config['semester'], config['directory'])
    except:
        logger.error("failed to initialize (maybe you forgot to specifiy username, password or semester?)")
        sys.exit(10)

    if options.sync:
        moodle.sync()
    if options.getDeadlines:
        moodle.getDeadlines()
    if options.getGrades:
        moodle.getGrades()