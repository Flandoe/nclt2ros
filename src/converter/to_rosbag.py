import rosbag
import os
import json
import subprocess
import sys

from src.extractor.read_sensor_data import ReadRawData
from src.transformer.sensor_data import RosSensorMsg
from src.transformer.hokuyo_data import HokuyoData
from src.transformer.velodyne_sync_data import VelodyneSyncData
from src.extractor.raw_data import RawData
from definitions import ROOT_DIR


class ToRosbag(RawData):
    """Class to convert the NCLT Dataset into a rosbag file

    USAGE:
            ToRosbag('2013-01-10', 'example.bag', cam_folder=None)

    """
    def __init__(self, date, bag_name, cam_folder=None):

        if isinstance(date, str):
            self.date = date
        else:
            raise TypeError('"date" must be of type string')

        # init base class
        RawData.__init__(self, date=self.date)

        # load class instances
        self.raw_data           = ReadRawData(self.date)
        self.ros_sensor_msg     = RosSensorMsg(self.date)
        self.hokuyo_data        = HokuyoData(self.date)
        self.velodyne_sync_data = VelodyneSyncData(self.date)
        #self.image_data = TransformImageData(self.date)

        # create rosbag file
        os.chdir(self.rosbag_dir)
        self.bag_name = str(bag_name)
        self.bag = rosbag.Bag(self.bag_name, 'w')

        # create camera folder settings
        self.num_cameras = 6
        self.data_dir = ROOT_DIR + '/raw_data/' + self.date
        self.images_dir = self.data_dir + '/images/' + '%s' % self.date + '/lb3/'

        if cam_folder is None:
            self.cam_folder = None
        elif isinstance(cam_folder, str):
            self.cam_folder = 'all'
        elif isinstance(cam_folder, int):
            if (cam_folder >= 0) and (cam_folder < 6):
                self.cam_folder = cam_folder
            else:
                raise ValueError("camera_topics must be between 0 and 5")
        else:
            raise TypeError("camera_topics must be a integer")

    def __del__(self):
        """destructor
        """

        self.bag.close()

    def process(self):
        """loads and converts the data into a rosbag file

        """
        # init counter with 0
        i_gt      = 0
        i_gps     = 0
        i_gps_rtk = 0
        i_ms25    = 0
        i_odom    = 0
        i_vel     = 0
        i_img     = 0

        print("loading data ...")

        # load ground_truth data
        gt_list       = self.raw_data.read_gt_csv(all_in_one=True)
        gt_cov_list   = self.raw_data.read_gt_cov_csv(all_in_one=True)

        # load sensor data
        gps_list      = self.raw_data.read_gps_csv(all_in_one=True)
        gps_rtk_list  = self.raw_data.read_gps_rtk_csv(all_in_one=True)
        ms25_list     = self.raw_data.read_ms25_csv(all_in_one=True)
        odom_list     = self.raw_data.read_odometry_mu_100hz_csv(all_in_one=True)
        odom_cov_list = self.raw_data.read_odometry_cov_100hz_csv(all_in_one=True)
        wheels_list   = self.raw_data.read_wheels_csv(all_in_one=True)
        kvh_list      = self.raw_data.read_kvh_csv(all_in_one=True)

        # load hokuyo data
        utime_hok4, data_hok4   = self.hokuyo_data.read_next_hokuyo_4m_packet()
        utime_hok30, data_hok30 = self.hokuyo_data.read_next_hokuyo_30m_packet()

        # load velodyne sync data
        vel_sync_timestamps_microsec, vel_sync_bin_files = self.velodyne_sync_data.get_velodyne_sync_timestamps_and_files()

        # load image data
        if self.cam_folder is not None:
            images_timestamps_microsec = self.image_data.get_image_timestamps()

        print("loaded data, writing to rosbag ...")

        max_num_messages = 1e20
        num_messages = 0

        while True:
            next_packet = "done"
            next_utime = -1

            if i_gps < len(gps_list) and (gps_list[i_gps, 0] < next_utime or next_utime < 0):
                next_utime = gps_list[i_gps, 0]
                next_packet = "gps"

            if i_gps_rtk < len(gps_rtk_list) and (gps_rtk_list[i_gps_rtk, 0] < next_utime or next_utime < 0):
                next_utime = gps_rtk_list[i_gps_rtk, 0]
                next_packet = "gps_rtk"

            if i_ms25 < len(ms25_list) and (ms25_list[i_ms25, 0] < next_utime or next_utime < 0):
                next_utime = ms25_list[i_ms25, 0]
                next_packet = "ms25"

            if i_gt < len(gt_list) and (gt_list[i_gt, 0] < next_utime or next_utime < 0):
                next_utime = gt_list[i_gt, 0]
                next_packet = "gt"

            if i_odom < len(odom_list) and (odom_list[i_odom, 0] < next_utime or next_utime < 0):
                next_utime = odom_list[i_odom, 0]
                next_packet = "odom"

            if utime_hok4 > 0 and (utime_hok4 < next_utime or next_utime < 0):
                next_packet = "hok4"

            if utime_hok30 > 0 and (utime_hok30 < next_utime or next_utime < 0):
                next_packet = "hok30"

            if i_vel < len(vel_sync_timestamps_microsec) and (vel_sync_timestamps_microsec[i_vel] < next_utime or next_utime < 0):
                next_utime = vel_sync_timestamps_microsec[i_vel]
                next_packet = "vel_sync"

            if self.cam_folder is not None:
                if i_img < len(images_timestamps_microsec) and (images_timestamps_microsec[i_img] < next_utime or next_utime < 0):
                    next_utime = images_timestamps_microsec[i_img]
                    next_packet = "img"

            print 'next_packet: ', next_packet

            if next_packet == "done":
                break

            elif next_packet == "gps":
                print("write gps")
                navsat, track, speed, timestamp, tf_static_msg = self.ros_sensor_msg.gps_to_navsat(gps_list=gps_list, i=i_gps)
                self.bag.write(self.json_configs['topics']['gps_sensor']['fix'], navsat, timestamp)
                self.bag.write(self.json_configs['topics']['gps_sensor']['track'], track, timestamp)
                self.bag.write(self.json_configs['topics']['gps_sensor']['speed'], speed, timestamp)
                self.bag.write('/tf_static', tf_static_msg, t=timestamp)
                i_gps += 1

            elif next_packet == "gps_rtk":
                print("write gps_rtk")
                navsat, track, speed, timestamp, tf_static_msg = self.ros_sensor_msg.gps_rtk_to_navsat(gps_rtk_list=gps_rtk_list, i=i_gps_rtk)
                self.bag.write(self.json_configs['topics']['gps_rtk_sensor']['fix'], navsat, t=timestamp)
                self.bag.write(self.json_configs['topics']['gps_rtk_sensor']['track'], track, t=timestamp)
                self.bag.write(self.json_configs['topics']['gps_rtk_sensor']['speed'], speed, t=timestamp)
                self.bag.write('/tf_static', tf_static_msg, t=timestamp)
                i_gps_rtk += 1

            elif next_packet == "ms25":
                print("write ms25")
                imu, mag, timestamp, tf_static_msg = self.ros_sensor_msg.ms25_to_imu(imu_list=ms25_list, i=i_ms25)
                self.bag.write(self.json_configs['topics']['ms25_sensor']['imu_data'], imu, t=timestamp)
                self.bag.write(self.json_configs['topics']['ms25_sensor']['imu_mag'], mag, t=timestamp)
                self.bag.write('/tf_static', tf_static_msg, t=timestamp)
                i_ms25 += 1

            elif next_packet == "odom":
                print("write odom")
                odom, timestamp, tf_msg, tf_static_msg = self.ros_sensor_msg.wheel_odom_to_odometry(odom_list=odom_list, odom_cov_list=odom_cov_list, wheels_list=wheels_list, kvh_list=kvh_list, i=i_odom)
                self.bag.write(self.json_configs['topics']['wheel_odometry'], odom, t=timestamp)
                self.bag.write('/tf', tf_msg, t=timestamp)
                self.bag.write('/tf_static', tf_static_msg, t=timestamp)
                i_odom += 1

            elif next_packet == "gt":
                print("write gt")
                gt, timestamp, tf_static_msg = self.ros_sensor_msg.gt_to_odometry(gt_list=gt_list, gt_cov_list=gt_cov_list, i=i_gt)
                self.bag.write(self.json_configs['topics']['ground_truth'], gt, t=timestamp)
                self.bag.write('/tf_static', tf_static_msg, t=timestamp)
                i_gt += 1

            elif next_packet == "hok4":
                print("write hok4")
                timestamp, scan, tf_static_msg = self.hokuyo_data.write_hokuyo_4m_to_laserscan(utime_hok4, data_hok4)
                self.bag.write(self.json_configs['topics']['hokuyo']['urg_lidar'], scan, t=timestamp)
                self.bag.write('/tf_static', tf_static_msg, t=timestamp)
                utime_hok4, data_hok4 = self.hokuyo_data.read_next_hokuyo_4m_packet()

            elif next_packet == "hok30":
                print("write hok30")
                timestamp, scan, tf_static_msg = self.hokuyo_data.write_hokuyo_30m_to_laserscan(utime_hok30, data_hok30)
                self.bag.write(self.json_configs['topics']['hokuyo']['utm_lidar'], scan, t=timestamp)
                self.bag.write('/tf_static', tf_static_msg, t=timestamp)
                utime_hok30, data_hok30 = self.hokuyo_data.read_next_hokuyo_30m_packet()

            elif next_packet == "vel_sync":
                print("vel_sync")
                try:
                    hits = self.velodyne_sync_data.read_next_velodyne_sync_packet(vel_sync_bin_files[i_vel])
                except ValueError:
                    print("Error velodyne")

                timestamp, pc2_msg, tf_static_msg = self.velodyne_sync_data.xyzil_array_to_pointcloud2(utime=vel_sync_timestamps_microsec[i_vel], hits=hits)
                self.bag.write(self.json_configs['topics']['velodyne_lidar'], pc2_msg, t=timestamp)
                self.bag.write('/tf_static', tf_static_msg, t=timestamp)
                i_vel += 1

            elif next_packet == "img":
                if self.cam_folder is 'all':
                    for camera_id in range(self.num_cameras):
                        cam_file = os.path.join(self.images_dir, 'Cam' + str(camera_id), str(next_utime) + '.tiff')
                        timestamp, image_msg, tf_static_msg = self.image_data.write_images(utime=next_utime, cam_file=cam_file)
                        self.bag.write(self.json_configs['topics']['ladybug_sensor'] + str(camera_id), image_msg, t=timestamp)
                        self.bag.write('/tf_static', tf_static_msg, t=timestamp)
                else:
                    cam_file = os.path.join(self.images_dir, 'Cam' + str(self.cam_folder), str(next_utime) + '.tiff')
                    timestamp, image_msg, tf_static_msg = self.image_data.write_images(utime=next_utime, cam_file=cam_file)
                    self.bag.write(self.json_configs['topics']['ladybug_sensor'] + str(self.cam_folder), image_msg, t=timestamp)
                    self.bag.write('/tf_static', tf_static_msg, t=timestamp)
                i_img += 1
            else:
                print "unkown packet type"

            num_messages += 1
            print 'num message: ', num_messages
            if num_messages >= max_num_messages:
                break

        print("successfully created rosbag file")
        self.bag.close()

        #self.compress_bag()

    def compress_bag(self):

        files = os.listdir(self.rosbag_dir)
        try:

            if self.bag_name in files:

                os.chdir(self.rosbag_dir)
                reindex_cmd = "rosbag reindex " + self.bag_name
                compress_cmd = "rosbag compress --lz4 " + self.bag_name

                #reindex_proc = subprocess.Popen(reindex_cmd, stdin=subprocess.PIPE, shell=True, executable='/bin/bash')
                #output, error = reindex_proc.communicate()
                #if error:
                #    print("error occured while running rosbag reindex")
                #    sys.exit(0)

                #reindex_proc.wait()

                compress_proc = subprocess.Popen(compress_cmd, stdin=subprocess.PIPE, shell=True, executable='/bin/bash')

                output, error = compress_proc.communicate()

                if error:
                    print("error occured while running rosbag compress")
                    sys.exit(0)

                compress_proc.wait()

                # remove orig file
                orig_bag_str = self.bag_name[:-4] + '.orig.bag'
                all_files = os.listdir(self.rosbag_dir)
                for f in all_files:
                    if f == orig_bag_str:
                        os.remove(f)

        except Exception as e:
            print(e)


if __name__ == '__main__':
    dtr = ToRosbag('2013-01-10', 'test3.bag')
    dtr.process()
    #dtr.compress_bag()