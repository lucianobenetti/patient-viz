#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Created on 2015-03-04

@author: joschi
"""
from __future__ import print_function
import time as time_lib
from datetime import datetime, timedelta
import shelve
import sys
import os.path
import csv
#import simplejson as json
import json
import BitVector

sys.path.append('..')

import build_dictionary
import opd_get_patient

path_correction = '../'
flush_threshold = 650

from_time = -float('Inf')
to_time = float('Inf')
age_time = None
age_bin = 7
ignore = {
    "prescribed": True
}

def toTime(s):
    return int(time_lib.mktime(datetime.strptime(s, "%Y%m%d").timetuple()))

def toAge(s):
    # TODO there could be a more precise way
    return datetime.fromtimestamp(toTime(s + "0101")).year - datetime.fromtimestamp(age_time).year

def handleRow(row, id, eventCache, infoCache):
    obj = {
        "info": [],
        "events": []
    }
    opd_get_patient.handleRow(row, obj)
    eventCache.extend(filter(lambda e: e['time'] >= from_time and e['time'] <= to_time and e['group'] not in ignore, obj["events"]))
    for info in obj["info"]:
        if info["id"] == "age":
            try:
                bin = (int(info["value"]) // age_bin) * age_bin
                infoCache.append("age_" + str(bin) + "_" + str(bin + age_bin))
            except ValueError:
                pass
        elif info["id"] == "born":
            try:
                if info["value"] != "N/A" and age_time is not None:
                    bin = (toAge(info["value"]) // age_bin) * age_bin
                    infoCache.append("age_" + str(bin) + "_" + str(bin + age_bin))
            except ValueError:
                pass
        elif info["id"] == "death" and info["value"] != "N/A":
            infoCache.append("dead")
        elif info["id"] == "gender":
            if info["value"] == "M":
                infoCache.append("sex_m")
            elif info["value"] == "F":
                infoCache.append("sex_f")


def processFile(inputFile, id_column, cb):
    print("processing file: {0}".format(inputFile), file=sys.stderr)
    id_event_cache = {}
    id_info_cache = {}

    def handleRows(csvDictReader):
        for row in csvDictReader:
            id = row[id_column]
            if id in id_event_cache:
                eventCache = id_event_cache[id]
            else:
                eventCache = []
            if id in id_info_cache:
                infoCache = id_info_cache[id]
            else:
                infoCache = []
            handleRow(row, id, eventCache, infoCache)
            if len(eventCache) > flush_threshold:
                processDict(eventCache, id)
                eventCache = []
            id_event_cache[id] = eventCache
            if len(infoCache) > 0:
                id_info_cache[id] = infoCache

    def processDict(events, id):
        if len(events) == 0:
            return
        print("processing {1} with {0} events".format(len(events), id), file=sys.stderr)
        obj = {
            "events": events
        }
        dict = {}
        build_dictionary.extractEntries(dict, obj)
        for group in dict.keys():
            cb(id, group, dict[group].keys())

    if inputFile == '-':
        handleRows(csv.DictReader(sys.stdin))
    else:
        with open(inputFile) as csvFile:
            handleRows(csv.DictReader(csvFile))

    num_total = len(id_event_cache.keys())
    num = 0
    last_print = 0
    for id in id_event_cache.keys():
        eventCache = id_event_cache[id]
        processDict(eventCache, id)
        del eventCache[:]
        num += 1
        if num / num_total > last_print + 0.01 or num == num_total:
            last_print = num / num_total
            print("processing file: {0} {1:.2%} complete".format(inputFile, last_print), file=sys.stderr)
    for id in id_info_cache.keys():
        infoCache = id_info_cache[id]
        cb(id, "info", infoCache)

def processDirectory(dir, id_column, cb):
    for (_, _, files) in os.walk(dir):
        for file in files:
            if file.endswith(".csv"):
                processFile(dir + '/' + file, id_column, cb)

def getBitVector(vectors, header_list, id):
    if id in vectors:
        bitvec = vectors[id]
    else:
        bitvec = BitVector.BitVector(size=0)
    if len(bitvec) < len(header_list):
        diff = len(header_list) - len(bitvec)
        bitvec = bitvec + BitVector.BitVector(size=diff)
    vectors[id] = bitvec
    return bitvec

def getHead(group, type):
    return group + "__" + type

def processAll(vectors, header_list, path_tuples):
    header = {}

    def handle(id, group, types):
        if "__" in group:
            print("group name is using __: {0}".format(group), file=sys.stderr)
        for type in types:
            head = getHead(group, type)
            if head not in header:
                header[head] = len(header_list)
                header_list.append(head)
        bitvec = getBitVector(vectors, header_list, id)
        for type in types:
            head = getHead(group, type)
            bitvec[header[head]] = True

    id_column = opd_get_patient.input_format["patient_id"]
    for (path, isfile) in path_tuples:
        if isfile:
            processFile(path, id_column, handle)
        else:
            processDirectory(path, id_column, handle)


def printResult(vectors, header_list, delim, quote, out):

    def doQuote(cell):
        cell = str(cell)
        if cell.find(delim) < 0 and cell.find(quote) < 0:
            return cell
        return  quote + cell.replace(quote, quote + quote) + quote

    str = doQuote("id") + delim + delim.join(map(doQuote, header_list))
    print(str, file=out)

    empty = BitVector.BitVector(size=0)
    for id in vectors.keys():
        bitvec = getBitVector(vectors, header_list, id)
        str = doQuote(id) + delim + delim.join(map(doQuote, map(lambda v: 1 if v else 0, bitvec)))
        vectors[id] = empty
        print(str, file=out)

def usage():
    print('usage: {0} [-h] [--from <date>] [--to <date>] [-o <output>] -f <format> -c <config> -- <file or path>...'.format(sys.argv[0]), file=sys.stderr)
    print('-h: print help', file=sys.stderr)
    print('--age-time <date>: specifies the date to compute the age as "YYYYMMDD". can be omitted', file=sys.stderr)
    print('--from <date>: specifies the start date as "YYYYMMDD". can be omitted', file=sys.stderr)
    print('--to <date>: specifies the end date as "YYYYMMDD". can be omitted', file=sys.stderr)
    print('-o <output>: specifies output file. stdout if omitted or "-"', file=sys.stderr)
    print('-f <format>: specifies table format file', file=sys.stderr)
    print('-c <config>: specify config file. "-" uses default settings', file=sys.stderr)
    print('<file or path>: a list of input files or paths containing them. "-" represents stdin', file=sys.stderr)
    exit(1)

if __name__ == '__main__':
    output = '-'
    settings = {
        'delim': ',',
        'quote': '"',
        'filename': build_dictionary.globalSymbolsFile,
        'ndc_prod': build_dictionary.productFile,
        'ndc_package': build_dictionary.packageFile,
        'icd9': build_dictionary.icd9File,
        'ccs_diag': build_dictionary.ccs_diag_file,
        'ccs_proc': build_dictionary.ccs_proc_file
    }
    args = sys.argv[:]
    args.pop(0)
    while args:
        arg = args.pop(0)
        if arg == '--':
            break
        if arg == '-h':
            usage()
        if arg == '--age-time':
            if not args or args[0] == '--':
                print('--age-time requires a date', file=sys.stderr)
                usage()
            age_time = toTime(args.pop(0))
        elif arg == '--from':
            if not args or args[0] == '--':
                print('--from requires a date', file=sys.stderr)
                usage()
            from_time = toTime(args.pop(0))
        elif arg == '--to':
            if not args or args[0] == '--':
                print('--to requires a date', file=sys.stderr)
                usage()
            to_time = toTime(args.pop(0))
        elif arg == '-f':
            if not args or args[0] == '--':
                print('-f requires format file', file=sys.stderr)
                usage()
            opd_get_patient.read_format(args.pop(0))
        elif arg == '-o':
            if not args or args[0] == '--':
                print('-o requires output file', file=sys.stderr)
                usage()
            output = args.pop(0)
        elif arg == '-c':
            if not args or args[0] == '--':
                print('-c requires argument', file=sys.stderr)
                usage()
            build_dictionary.readConfig(settings, args.pop(0))
        else:
            print('unrecognized argument: ' + arg, file=sys.stderr)
            usage()

    build_dictionary.globalSymbolsFile = path_correction + settings['filename']
    build_dictionary.icd9File = path_correction + settings['icd9']
    build_dictionary.ccs_diag_file = path_correction + settings['ccs_diag']
    build_dictionary.ccs_proc_file = path_correction + settings['ccs_proc']
    build_dictionary.productFile = path_correction + settings['ndc_prod']
    build_dictionary.packageFile = path_correction + settings['ndc_package']
    build_dictionary.reportMissingEntries = False
    build_dictionary.init()

    allPaths = []
    while args:
        path = args.pop(0)
        if os.path.isfile(path) or path == '-':
            allPaths.append((path, True))
        elif os.path.isdir(path):
            allPaths.append((path, False))
        else:
            print('illegal argument: '+path+' is neither file nor directory', file=sys.stderr)

    vectors = {}
    header_list = []
    processAll(vectors, header_list, allPaths)
    if output == '-':
        printResult(vectors, header_list, settings['delim'], settings['quote'], sys.stdout)
    else:
        with open(output, 'w') as file:
            printResult(vectors, header_list, settings['delim'], settings['quote'], file)
