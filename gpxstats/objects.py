import os
import re
import sys
# import pickle
import sqlite3
import inspect
from datetime import datetime
from math import radians, cos, sin, asin, sqrt
from gpxstats import processors, parsers


class Coordinate(object):

	def __init__(self, lat, lon, ele):
		self.lon = lon
		self.lat = lat
		self.ele = ele

	def __str__(self):
		return (
			'(' + (str(self.lat) + ',' + str(self.lon)).ljust(21) + 
			' el:' + str(self.ele).ljust(6) + ')'
		)

	def dist(self, c2):
		d_lon = c2.lon - self.lon
		d_lat = c2.lat - self.lat
		d_ele = c2.ele - self.ele

		lon_m = self.lon + d_lon * 0.5
		lat_m = self.lat + d_lat * 0.5
		ele_m = self.ele + d_ele * 0.5

		R = 6367000.0  # Radius of Earth in meters

		d1 = R * radians(d_lon) * cos( radians(lat_m) )
		d2 = R * radians(d_lat)
		return sqrt(d1**2 + d2**2 + d_ele**2)


class Point(object):
	time = None
	speed = None
	course = None
	cord = None
	
	last = None
	
	dist = None
	speed_calc = None
	acceleration_calc = None

	def __init__(self, full_string, last, next_last):
		# Extract fields from the gpx archive text
		time = parsers.extract_field(full_string, 'time')
		self.time = datetime.strptime(time, '%Y-%m-%dT%H:%M:%SZ')
		speed = parsers.extract_field(full_string, 'speed')
		self.speed = float(speed) if type(speed) is str else None
		course = parsers.extract_field(full_string, 'course')
		self.course = float(course) if type(course) is str else None
		(lat, lon) = parsers.extract_cords(full_string)
		ele = float(parsers.extract_field(full_string, 'ele'))
		self.cord = Coordinate(lat, lon, ele)
		# Calculated fields
		if last is not None:
			# distance from last point
			self.dist = self.cord.dist(last.cord)
			# speed calculation
			deltat = (self.time - last.time).total_seconds()
			self.speed_calc =  self.dist / deltat
			# acceleration calculation
			if next_last is not None:
				v1 = self.speed_calc
				v2 = last.speed_calc
				deltat = 0.5 * self.delta_time(next_last)
				deltav = float(v1) - v2
				self.acceleration_calc = deltav/deltat
			else:
				self.acceleration_calc = None
		else:
			self.speed_calc = None
			self.acceleration_calc = None

	def __str__(self):
		if self.speed is None:
			return 'stopped at             ' + str(self.time)
		else:
			return 'moving ' + str(round(self.speed*2.23694,2)).ljust(5) + ' mph ' + str(self.cardnal()) + ' at ' + str(self.time)

	def delta_time(self, point2):
		return (self.time - point2.time).total_seconds()

	def full_print(self):
		return self.__str__() + '  ' + self.cord.__str__()

	def cardnal(self):
		if self.course is None:
			return 'stationary'
		else:
			ang45 = (self.course + 45.) % 360.
			dirs = ['N', 'E', 'S', 'W']
			dint = int(ang45/90.)
			d = dirs[dint]
			ang_sm = ang45 % 90.
			if ang_sm < 90./3.:
				return dirs[dint] + dirs[(dint-1) % 4]
			elif ang_sm < 90.*2./3.:
				return dirs[dint].ljust(2)
			else:
				return (dirs[dint] + dirs[(dint-1) % 4]).ljust(2)

	@property
	def elevation(self):
		return self.cord.ele


class Archive(object):
	filelist = None
	archive_dir = None

	i_file = None
	i_pattern = None

	point_list = None
	
	last = None
	next_last = None

	def __init__(self, path='archive/', save='save/tracks.db', cache=False):
		cwd = os.getcwd()
		save_dir = os.path.join(cwd, save)

		if os.path.isdir(save_dir) and cache:
			dest_filename = os.path.join(cwd, 'save/points_pickle.p')
			if os.path.isfile(dest_filename):
				self.point_list = pickle.load( open( dest_filename, "rb" ) )
				self.working_point_index = 0

		if path.startswith('/'):
			self.archive_dir = os.listdir(path)
		else:
			self.archive_dir = os.path.join(cwd, path)
		raw_filelist = os.listdir(self.archive_dir)

		filelist = []
		for f in raw_filelist:
			if len(f) > 4 and f[-4:] == '.gpx':
				filelist.append(f)

		# Sort file list numerically, not alphabetically
		filelist = sorted(filelist, key=lambda x: float(x[:-4]))

		if len(filelist) == 0:
			raise Exception('Did not find any gpx files in archive dir')

		if cache and self.point_list is None:
			pt_list = []
			for filename in filelist:
				patern_list = self.load_list_from_file(filename)
				for pattern in patern_list:
					pt_list.append(Point(pattern))
			self.point_list = pt_list
			dest_filename = os.path.join(cwd, 'save/points_pickle.p')
			pickle.dump(self.point_list, open(dest_filename, 'wb'))

		# Set iterables to the starting position
		self.i_file = iter(filelist)
		self.i_pattern = iter([])
		self.last = None
		self.next_last = None

	def __str__(self):
		return 'gpx archive with ' + str(len(self.filelist)) + ' files'

	def __iter__(self):
		return self

	def __next__(self):
		if self.point_list:
			if self.working_point_index > len(self.point_list):
				raise StopIteration
			return self.point_list[self.working_point_index]
			self.working_point_index += 1
		else:
			try:
				next_pattern = self.i_pattern.__next__()
			except StopIteration:
				# If this raises StopIteration, let it be
				filename = self.i_file.__next__()
				self.load_list_from_file(filename)
				next_pattern = self.i_pattern.__next__()
			pt = Point(next_pattern, self.last, self.next_last)
		self.next_last = self.last
		self.last = pt
		return pt

	def load_list_from_file(self, filename):
		sys.stdout.write('New file: ' + filename + '\n')
		with open(os.path.join(self.archive_dir, filename), 'r') as f:
			full_file = f.read()
		pattern = '(?P<trkpt>\<trkpt.*?\/trkpt\>)'
		pattern_list = re.findall(pattern, full_file)
		self.i_pattern = iter(pattern_list)
		return pattern_list


class Analyzer(object):
	archive = None
	proc_list = None
	
	def __init__(self, **kwargs):
		self.archive = Archive(**kwargs)
		proc_names = [p for p in dir(processors)]
		self.proc_list = []
		sys.stdout.write('Running processors: \n')
		for proc_name in proc_names:
			if not proc_name[0].isupper():
				continue
			sys.stdout.write(' - ' + proc_name + '\n')
			ProcessorClass_ = getattr(processors, proc_name)
			sys.stdout.write('proc: ' + proc_name + '\n')
			proc_instance = ProcessorClass_()
			self.proc_list.append(proc_instance)
		
	def go(self):
		# Start iteration over all points in the archive
		for pt in self.archive:
			for proc in self.proc_list:
				proc.update(pt)
		# Show the fruits of our labors on the terminal
		for proc in self.proc_list:
			proc.display()
	