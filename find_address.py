# Final *****
from __future__ import division, print_function # python2
from PyGeoTools.geolocation import GeoLocation
from collections import namedtuple
import sqlite3
import json
import time
import shapefile
import os

connection = sqlite3.connect(os.path.abspath("Myanmar" + os.sep + "Myanmar-OSM-March.db"))
check_flag = False

""" Mathematical calculation to get result that two rectangles intersect or not-intersect """
""" Returns 'None' if rectangles don't intersect """
""" b means boundary values from database and arrangement is min_lon, max_lon, min_lat, max_lat """
def check_inside_which_way(lat, lon, b, bbox_range=0.02286): 
    BBox = namedtuple('BBox', 'min_lon max_lon min_lat max_lat')
    small_min_bbox, small_max_bbox = GeoLocation.from_degrees(lat, lon).bounding_locations(bbox_range) #75-ft bbox    
    ra = BBox(small_min_bbox.deg_lon, small_max_bbox.deg_lon, small_min_bbox.deg_lat, small_max_bbox.deg_lat)
    rb = BBox(b[1],b[2],b[3],b[4])
    dx = min(ra.max_lon, rb.max_lon) - max(ra.min_lon, rb.min_lon)
    dy = min(ra.max_lat, rb.max_lat) - max(ra.min_lat, rb.min_lat)
    if (dx>=0) and (dy>=0):
        return dx*dy 
    
""" Mathematical calculation to produce numbers of points """
""" Returns (x, y) points values between two boundary points """
""" x_spacing, y_spacing means SLOPES of a line on Coordinate """
""" nb_points means how much points you need, default is 13 """
def intermediates(lat, lon, actual_location, b, nb_points=13):
    x_spacing = (b[2] - b[1]) / (nb_points + 1)
    y_spacing = (b[4] - b[3]) / (nb_points + 1)
    return  min([actual_location.distance_to(GeoLocation.from_degrees(p[0],p[1])) 
                for p in [(b[3]+i*y_spacing, b[1]+i*x_spacing) for i in range(1, nb_points+1)]])

""" Get polyline points values and calculate which is the actual way by that points """
""" Containt trick of calculation when a points is on Junctions """
def check_by_polyline_points(lat, lon, actual_location, result_overlap):
    nearest_way=[]
    polyline_points = [(b[0], tuple(json.loads(connection.execute(
                      "SELECT points FROM polyline_points WHERE id=?", (b[0],)).fetchall()[0][0]))) for b in result_overlap]
    if not check_flag:
        for each_line in polyline_points:
            points = each_line[1]
            checking_points = [(p[0], p[1][1], p[1][0], actual_location.distance_to(GeoLocation.from_degrees(p[1][1], p[1][0]))) for p in enumerate(points)]
            enum = checking_points[min(range(len(checking_points)), key=lambda i: checking_points[i][3])][0]
            if len(checking_points) > 2:
                if enum == 0:
                    side_points = (each_line[0], checking_points[enum+1][2], checking_points[enum][2], checking_points[enum+1][1], checking_points[enum][1])
                elif enum == len(checking_points)-1:
                    side_points = (each_line[0], checking_points[enum][2], checking_points[enum-1][2], checking_points[enum][1], checking_points[enum-1][1])
                else: 
                    side_points = (each_line[0], checking_points[enum+1][2], checking_points[enum-1][2], checking_points[enum+1][1], checking_points[enum-1][1])                
                nearest_way.append((each_line[0], intermediates(lat, lon, actual_location, side_points)))
            elif len(checking_points) == 2: 
                side_points = (each_line[0], checking_points[1][2], checking_points[0][2], checking_points[1][1], checking_points[0][1])
                nearest_way.append((each_line[0], intermediates(lat, lon, actual_location, side_points)))
        return [nearest_way[min(range(len(nearest_way)), key=lambda i: nearest_way[i][1])][0]]
    elif check_flag:
        for each_line in polyline_points:
            points = each_line[1]
            checking_points = [(p[0], p[1][1], p[1][0], actual_location.distance_to(GeoLocation.from_degrees(p[1][1], p[1][0]))) for p in enumerate(points)]
            nearest_way.append((each_line[0], checking_points[min(range(len(checking_points)), key=lambda i: checking_points[i][3])][3]))
        return [nearest_way[min(range(len(nearest_way)), key=lambda i: nearest_way[i][1])][0]]
            
""" The initial function of finding way """
""" First get all possible ways around 3000ft from database """
def search_nearest_way(lat, lon, bbox_range):
    global check_flag
    nearest_ways = []
    actual_location = GeoLocation.from_degrees(lat, lon)
    min_bbox, max_bbox = actual_location.bounding_locations(bbox_range)
    nearest_ways.extend(connection.execute(
                        "SELECT * FROM idx_polylines_name_geometry WHERE "+
                        "ymin BETWEEN "+ str(min_bbox.deg_lat)+ " AND "+ str(lat)+ " AND "+
                        "xmin BETWEEN "+ str(min_bbox.deg_lon)+ " AND "+ str(lon)+ " OR "+
                        "ymax BETWEEN "+ str(lat)+ " AND "+ str(max_bbox.deg_lat)+ " AND "+
                        "xmax BETWEEN "+ str(lon)+ " AND "+ str(max_bbox.deg_lon)).fetchall())
    result_overlap = [b for b in nearest_ways if not check_inside_which_way(lat, lon, b) == None]
    nearest_by_overlap = [each[0] for each in result_overlap]
    if len(nearest_by_overlap) == 1:
        return nearest_by_overlap
    elif len(nearest_by_overlap) > 1:
        return check_by_polyline_points(lat, lon, actual_location, result_overlap)        
    elif len(nearest_by_overlap) == 0:
        result_overlap = [b for b in nearest_ways if not check_inside_which_way(lat, lon, b, 0.04572) == None]
        if result_overlap:
            return check_by_polyline_points(lat, lon, actual_location, result_overlap)
        elif not result_overlap:
            result_overlap = [b for b in nearest_ways if not check_inside_which_way(lat, lon, b, 0.13716) == None]
            if result_overlap:
                return check_by_polyline_points(lat, lon, actual_location, result_overlap)                
            else:
                check_flag = True
                result_overlap = [b for b in nearest_ways if not check_inside_which_way(lat, lon, b, 1.2) == None]
                return check_by_polyline_points(lat, lon, actual_location, result_overlap)

""" After doing all searching algorithms get 1 osm-id that is the name of the actual way """
""" Get way name by osm-id and from database and returns it """
def get_nearest_way(lat, lon):
    bbox_range = 1.2
    idx = search_nearest_way(lat, lon, bbox_range)
    try:
        nearest_way_name = [connection.execute("SELECT name FROM polylines_name WHERE id in ({0})".format(", ".join("?" for _ in idx)), idx).fetchall()[0][0]]
    except: pass
    finally:
        return nearest_way_name

""" Mathematical calculation by polygon boundary points to know inside which boundary """
""" points means polygon boundary points values get from boundary shp files """
""" Return True if a coordinate (x, y) is inside a polygon defined by
    a list of verticies [(x1, y1), (x2, x2), ... , (xN, yN)].
    Reference: http://www.ariel.com.au/a/python-point-int-poly.html via
    http://okomestudio.net/biboroku/?p=986
"""
def check_inside_which_boundary(x, y, points):
    n = len(points)
    inside = False
    p1x, p1y = points[0]
    for i in range(1, n + 1):
        p2x, p2y = points[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside

""" The initial function of finding boundary names via shp files """
""" This is the handler of check_inside_which_boundary function """
def search_boundaries(lat, lon, boundary_shp_file):
    outer = shapefile.Reader(os.path.abspath("Myanmar"+ os.sep + boundary_shp_file))
    outer_boundaries  = [each.bbox for each in outer.iterShapes()][1:]
    outer_boundary_name = outer.record(0)[2]
    inner_boundary_name = [nb for i, nb in [(i, pbs[2]) for i, pbs in [(i, outer.record(i)) for i in [i+1 for i, v in 
                           enumerate([lat < outer_boundaries[l][1] or lat > outer_boundaries[l][3] or
                                      lon < outer_boundaries[l][0] or lon > outer_boundaries[l][2] for l in range(len(outer_boundaries))
                                     ]) if v==False]]] if check_inside_which_boundary(lon, lat, outer.shape(i).points)]
    return inner_boundary_name, outer_boundary_name

""" After getting boundary names of shp files arrange them as Township, City, District or Region and State """
""" There is a trick technique if the boundary is Shan State because of it is too big and separated as Shan State Inner """
""" After arrangement returns it """
def get_boundaries(lat, lon):
    boundary_names = []
    outer_state_region_name, country_name = search_boundaries(lat, lon, 'Myanmar.shp')
    inner_state_district_name, un_need = search_boundaries(lat, lon, outer_state_region_name[0]+".shp")
    inner_state_district_name.reverse()    
    if outer_state_region_name[0] == "Shan State":
        city_township_name, b1 = search_boundaries(lat, lon, "Shan State Inner.shp")
        city_township_name.reverse()
        boundary_names.extend(city_township_name)    
    boundary_names.extend(inner_state_district_name)    
    boundary_names.extend([outer_state_region_name[0], country_name])     
    return boundary_names

""" The Main Handler of all functions inside this program """
""" All function calls start from here """
""" Combine way name and boundar names """
def get_address(lat, lon):
    global check_flag
    address = []
    try:
        address.extend(get_nearest_way(lat, lon))
        if check_flag: 
            address.insert(0, address.pop(0)+" (Possible Nearest Way)")
            check_flag = False
    except: pass
    try:
        address.extend(get_boundaries(lat, lon))
    except: pass  
    #print("{0}".format(", ".join(_ for _ in address)))
    #return u"{0}".format(", ".join(_ for _ in address)) # python2
    return "{0}".format(", ".join(_ for _ in address))


#start_time = time.time()
#get_address(16.7605, 96.5260)
#print('Searching Time:', time.time()-start_time)

# OR
	
if __name__ == "__main__":
    while(True):
        try:
            #lat, lon = raw_input("Enter LAT and LON: ").strip().split(',') # python2
            lat, lon = input("Enter LAT and LON: ").strip().split(',') # python3		
        except Exception as e:
            print(e)
        try: 
            start_time = time.time()
            print(get_address(float(lat), float(lon)))
            print('Searchin Time:', time.time()-start_time)
        except Exception as e: 
            print(e)
        finally:
            print('~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~')
