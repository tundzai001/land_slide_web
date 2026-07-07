//using GMap.NET;
//using GMap.NET.WindowsForms;
//using Newtonsoft.Json;
//using NTRIPCaster.Configs;
//using PointNav.CASTER;
//using PointNav.Navigation;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using System.Xml.Serialization;
//using uPLibrary.Networking.M2Mqtt;
//using uPLibrary.Networking.M2Mqtt.Messages;


namespace WF_GNSS_Adj
{
    public class base_t
    {
    public String obs_file="";
	public double[] antenna=new double[3];
	public int pos_opt=0;
	public Point3D pos=new Point3D();
    public string[] pos_str = new string[3];
    public bool fix = false;
    public double req_acc = 1.5;
    public double dis_acc_a;
    public double dis_acc_b;
    public double ang_acc;
           
    }

    public class stk_point
    {
        public int id=0;
        public string name = "";
        public Point3D NEH = new Point3D();
        //public PointLatLng gmapll { get; set; }
        public int pos_opt = 0;
        public double r_Acc = 0.005;
        public bool selected = false;
    }

    public class stk_meas
    {
        public int id = 0;
        public s_station station_point;
        //public rtkpoint target_point;
        public stk_point stake_point; 
        public Point3D dNEH = new Point3D();
        public double distance = 0;
        public double Hang = 0;
        public double r_Acc = 0.005;
      

    }

    public class s_station
    {
        public String name = "";
        public double ins_height = new double();
        public int pos_opt = 0;
        public Point3D pos = new Point3D();
        public string[] pos_str = new string[3];
        public bool fix = false;
        public double req_acc = 3;
        public bool update = false;
        public Point3D llh = new Point3D();
        public Point3D Appneu = new Point3D();// Approximated NEU
        public Point3D Adjneu = new Point3D();// Approximated NEU
        public Point3D std = new Point3D();// adjusted std
        public double a_const=2;
        public double b_const=2;
        public double mB=2;
        public bool processed = false;
        public List<m_distance> listDis = new List<m_distance>();
        public List<m_angle> lisAng = new List<m_angle>();


    }

    public class m_distance
    {
        public int No = 0;
        public string from = "";
        public string to = "";
        public double dis = 0;
        public double disAcc = 0;
        public double pH = 0;
        public double pCons = 0;
        public mopoint frompoint;
        public mopoint topoint;
        public double pdis = 0;
        public double ldis = 0;
        public double disAcc_a = 0;
        public double disAcc_b = 0;
    }

    public class m_angle
    {
        public int No = 0;
        public string left = "";
        public string middle = "";
        public string right = "";
        public double Hang = 0;
        public double angAcc = 0;
        public double Vang = 0;
        public mopoint leftpoint;
        public mopoint middlepoint;
        public mopoint rightpoint;
        public double lang = 0;
        public double pang = 0;
    }

  



        public class rtmp_opt// public class Globalvar
    {
        public int prc_duration = 60;//minute
        public int prc_interval=1;//second
        public double ratio_thres=3.0;
        public double hstd_thres=10.0142;//m
        public double vstd_thres = 10.010;//m
        public double fs_thres=0.0001;
        public double ppm_theres = 0.0001;
        public bool backward = true;
        public int n_point;
        public int InputType = 0;
        [XmlIgnore]
        //public MqttClient publisher;
        //public MQTT_Opt mqttopt = new MQTT_Opt();

        public int angle_format = 0;//0 decimal degree; 1 dd mm ss.ss 
        [XmlIgnore]
        public List<mopoint> list_mopoint=new List<mopoint>();
        [XmlIgnore]
        public List<mopoint> list_fixpoint = new List<mopoint>();
        [XmlIgnore]
        public List<mopoint> list_adjpoint = new List<mopoint>();
        [XmlIgnore]
        public List<mopoint> list_G_adjpoint = new List<mopoint>();
        //[XmlIgnore]
        //public List<rtkpoint> list_rtkpoint = new List<rtkpoint>();
        
        [XmlIgnore]
        public List<moloop> list_moloop = new List<moloop>();
        [XmlIgnore]
        public List<moloop> list_proloop= new List<moloop>();
        [XmlIgnore]
        public List<mobaseline> list_mobaseline=new List<mobaseline>();
        [XmlIgnore]
        public List<mobaseline> list_passedmobaseline = new List<mobaseline>();
        [XmlIgnore]
        public List<mobaseline> list_probaseline = new List<mobaseline>();
        [XmlIgnore]
        public List<mobaseline> list_adjbaseline = new List<mobaseline>();
        
       
        
        public int n_loop = 0;
        public double L0=105.0*Math.PI/180.0;
        public double k0 = 0.9999;
        public int nfix = 0;
        public int bq_opt = 0;// Baseline quality option for processing: 0 processed baseline; 1 passed baseline
        public double ref_scale = 0.001;
        public double ref_std = 0.0;
        public string reportfile = "";
        public string freport = "";
        public double[] V;
        public int iniround = 0;
        public bool dis_report = true;
        public float cur_time = 0;
        public bool clear_processed_data = false;
        public bool store_data = true;
        [XmlIgnore]
        public System.IO.StringWriter tmp_String = new StringWriter();
        public int aipos_version = 1;
        public bool adj_flag = true;
        public bool report_flag = true;
        public int tcp_port = 3001;
        [XmlIgnore]
        public TcpListener sever = null;
        public int rtk_interval = 5;
        public int rtk_filter = 0;
        [XmlIgnore]
        public Process raw_data_process;

        public int input_type = 1;
        public string comport = "COM7";
        public int RTK_port = 352;
        public int Raw_port = 350;
        public string Raw_path = "D:\\Aitogy\\RTM_data";
        public string Result_path = "";
        public int extratime = 10;
        public bool raw_data_process_opt = false;
        public int raw_data_input_method = 2;//0: static 1:ftp, 2: sopcat
        public int dis_cal_method = 1; //0: from previos, 1: from initial; 2; from first static
        public double std_thres_ini = 0.1;
        public int num_meas_ini = 50;
        public int num_refresh = 50;
        public bool data_from_file = false;
        public int sleep_time = 100;
        public double RTK_Hstd_thres = 0.0142;
        public double RTK_Vstd_thres = 0.010;

        public bool GPS_come = false;
        public int Pro_Method = 0;//0: Kalman Filter; 1: Moving Weighted
      
        public int dataFormat = 0;// 0:NMEA, 1: Ainav; 2: bin PVT
        public bool isplaying = false;
        public bool appcal_flag = true;
        public bool adjcal_flag = false;

     

        public static rtmp_opt read_from_file(string filename)
        {

            rtmp_opt rtmopt = new rtmp_opt();
            XmlSerializer xs = new XmlSerializer(typeof(rtmp_opt));
            using (StreamReader rd = new StreamReader(filename))
            {
                rtmopt = (rtmp_opt)xs.Deserialize(rd);
                rd.Close();
            }
            return rtmopt;
        }
        /// <summary>
        /// In dữ liệu kiểu Globalvar ra file
        /// </summary>
        /// <param name="filename"></param>
        /// <param name="globalvar"></param>
        public static void print_to_file(string filename, rtmp_opt rtmopt)
        {
            XmlSerializer xs = new XmlSerializer(typeof(rtmp_opt));
            using (StreamWriter wr = new StreamWriter(filename))
            {
                xs.Serialize(wr, rtmopt);
                wr.Close();
            }
        }

        public void print_Baseline_to_String()
        {
            tmp_String.Write("-------------Calculated Baselines-------------"); tmp_String.WriteLine();
            tmp_String.Write("Stt From_Point  To_Point d_north d_east dH dn_std de_std dH_sdt Length ratio"); tmp_String.WriteLine();
            for (int i = 0; i < list_probaseline.Count; i++)
            {
                //outfile.Write("%d %s %s %12.3f %12.3f %12.3f %12.3f %12.3f %12.3f %12.3f %12.3f",rtmpopt.list_probaseline[i].dneu.X rtmpopt.list_probaseline[i].dneu.Y, rtmpopt.list_probaseline[i].dneu.Z
                tmp_String.Write((i + 1).ToString() + " ");
                tmp_String.Write(list_probaseline[i].frompoint.basename + "  ");
                tmp_String.Write(list_probaseline[i].topoint.basename);
         
                tmp_String.Write(String.Format("  {0:F3} {1:F3} {2:F3}", list_probaseline[i].dneu.X, list_probaseline[i].dneu.Y, list_probaseline[i].dneu.Z));
                tmp_String.Write(String.Format("  {0:F5} {1:F5} {2:F5}", list_probaseline[i].std.X, list_probaseline[i].std.Y, list_probaseline[i].std.Z));
                tmp_String.Write(String.Format("  {0:F3}", list_probaseline[i].length));
                tmp_String.Write(String.Format("  {0:F2}", list_probaseline[i].ratio));
                tmp_String.WriteLine();
            }
            
        }

        public void Print_report_tofile()
        {
            try
            {
               
                System.IO.StreamWriter outfile = new System.IO.StreamWriter(reportfile); // Open filtered file
                outfile.Write("===========ADJUSTMENT REPORT==============="); outfile.WriteLine();
                outfile.Write("RTMonitoring Version 1.2"); outfile.WriteLine();
                outfile.WriteLine("Time: "+ System.DateTime.Now.ToString());

                outfile.Write(tmp_String.ToString());
                tmp_String.Close();
                outfile.Write("----------------Found loops-----------------"); outfile.WriteLine();
                outfile.Write("Stt List of Point df_north df_east dfH fs Length fs/s"); outfile.WriteLine();
                for (int i = 0; i < list_moloop.Count(); i++)
                {
                    outfile.Write((i + 1).ToString() + " ");
                    for (int j = 0; j < list_moloop[i].listmopoint.Count(); j++)
                        outfile.Write(list_moloop[i].listmopoint[j].basename + "  ");

                    outfile.Write(String.Format("  {0:F5} {1:F5} {2:F5}", list_moloop[i].fneu.X, list_moloop[i].fneu.Y, list_moloop[i].fneu.Z));
                    outfile.Write(String.Format("  {0:F5}", list_moloop[i].fs));
                    outfile.Write(String.Format("  {0:F3}", list_moloop[i].length));
                    outfile.Write(String.Format("  1/{0:F0}", list_moloop[i].ppm));
                    outfile.WriteLine();
                }
                outfile.Write("====================Adjustment result========================="); outfile.WriteLine();
                outfile.Write("------------Adjusted Baselines---------------"); outfile.WriteLine();
                outfile.Write("Stt From_Point To_Point Vdn Vde VdH Ad_north Ad_east AdH  Alength"); outfile.WriteLine();
                for (int i = 0; i < list_adjbaseline.Count(); i++)
                {
                    //outfile.Write("%d %s %s %12.3f %12.3f %12.3f %12.3f %12.3f %12.3f %12.3f %12.3f",list_probaseline[i].dneu.X list_probaseline[i].dneu.Y, list_probaseline[i].dneu.Z
                    outfile.Write((i + 1).ToString() + " ");
                    outfile.Write(list_adjbaseline[i].frompoint.basename + "  ");
                    outfile.Write(list_adjbaseline[i].topoint.basename);

                    outfile.Write(String.Format("  {0:F3} {1:F3} {2:F3}", V[i * 3], V[i * 3 + 1], V[i * 3 + 2]));
                    outfile.Write(String.Format("  {0:F3} {1:F3} {2:F3}", list_adjbaseline[i].dneu.X, list_adjbaseline[i].dneu.Y, list_adjbaseline[i].dneu.Z));
                    outfile.Write(String.Format("  {0:F3}", list_adjbaseline[i].length));
                    //outfile.Write(String.Format("  {0:F2}", list_probaseline[i].ratio));
                    outfile.WriteLine();
                }
                outfile.Write("-------------------Adjusted loops----------------"); outfile.WriteLine();
                outfile.Write("No List of Point df_north df_east dfH fs Length"); outfile.WriteLine();

                for (int i = 0; i < list_proloop.Count(); i++)
                {
                    outfile.Write((i + 1).ToString() + " ");
                    for (int j = 0; j < list_proloop[i].listmopoint.Count(); j++)
                    {
                      
                        outfile.Write(list_proloop[i].listmopoint[j].basename + "  ");
                    }

                        outfile.Write(String.Format("  {0:F7} {1:F7} {2:F7}", list_proloop[i].fneu.X, list_proloop[i].fneu.Y, list_proloop[i].fneu.Z));
                        outfile.Write(String.Format("  {0:F7}", list_proloop[i].fs));
                        outfile.Write(String.Format("  {0:F3}", list_proloop[i].length));
                        outfile.WriteLine();
                    
                }

                outfile.Write("-------------Control Point-----------------"); outfile.WriteLine();
                outfile.Write("Stt Point_name North East H"); outfile.WriteLine();
                for (int i = 0; i < list_fixpoint.Count(); i++)
                {
                    outfile.Write((i + 1).ToString() + " ");
                    outfile.Write(list_fixpoint[i].basename + "  ");
                    outfile.Write(String.Format("  {0:F3} {1:F3} {2:F3}", list_fixpoint[i].Appneu.X, list_fixpoint[i].Appneu.Y, list_fixpoint[i].Appneu.Z));
                    //outfile.Write(String.Format("  {0:F3} {1:F3} {2:F3}", list_adjpoint[i].std.X, list_adjpoint[i].std.Y, list_adjpoint[i].std.Z));
                    //outfile.Write(String.Format("  {0:F2}", list_probaseline[i].ratio));
                    outfile.WriteLine();
                    //list_fixpoint[i].llh = BL2xy.vn20002llh(L0, k0, list_mopoint[i].Appneu);
                    //list_fixpoint[i].gmapll = new GMap.NET.PointLatLng(list_mopoint[i].llh.X, list_mopoint[i].llh.Y);
                    //mopoint.Draw_mopoint(list_fixpoint[i]);

                }

                if (list_adjpoint.Count() > 0)
                {
                    outfile.Write("---------------Adjusted Point-------------"); outfile.WriteLine();
                    outfile.Write("Stt Point_name North(m) East(m) H(m) N-std(m) E-Std(m) H-Std(m)"); outfile.WriteLine();
                    for (int i = 0; i < list_adjpoint.Count(); i++)
                    {
                        outfile.Write((i + 1).ToString() + " ");
                        outfile.Write(list_adjpoint[i].basename + "  ");
                        outfile.Write(String.Format("  {0:F3} {1:F3} {2:F3}", list_adjpoint[i].Adjneu.X, list_adjpoint[i].Adjneu.Y, list_adjpoint[i].Adjneu.Z));
                        outfile.Write(String.Format("  {0:F3} {1:F3} {2:F3}", list_adjpoint[i].std.X, list_adjpoint[i].std.Y, list_adjpoint[i].std.Z));
                        //outfile.Write(String.Format("  {0:F2}", list_probaseline[i].ratio));
                        outfile.WriteLine();
                        //mopoint.Draw_mopoint(list_adjpoint[i]);

                    }

                }
                outfile.Write("------------Reference Standard Deviation-------------"); outfile.WriteLine();
                outfile.Write(String.Format(" M = {0:F3}", ref_std));
                outfile.WriteLine();
                
                outfile.Close();

                //list_mopoint.Clear();
                //list_fixpoint.Clear();
                //list_adjpoint.Clear();
                //list_moloop.Clear();
                //list_proloop.Clear();
                //list_mobaseline.Clear();
                //list_passedmobaseline.Clear();
                //list_probaseline.Clear();

            }
            catch (Exception)
            {
                MessageBox.Show("Error in open report file");
            }
        }
        
        
        
    }

   
    
    public class RePoint
    {
        /// <summary>
        /// Tên điểm
        /// </summary>
        public string name;
        /// <summary>
        /// Chu kỳ hiện thời
        /// </summary>
        public int cur_round;
        /// <summary>
        /// Thời gian hiện thời
        /// </summary>
        public double cur_time;
        [XmlIgnore]
        public double initime;
        [XmlIgnore]
        public double cur_time_tic;
        /// <summary>
        /// Toa do khoi dau
        /// </summary>
        public Point3D ini_NEH = new Point3D();
        /// <summary>
        /// Tọa độ điểm hiện thời
        /// </summary>
        public Point3D cur_NEH = new Point3D();
                /// <summary>
        /// Tọa độ điểm của chy kỳ trước
        /// </summary>
        public Point3D pre_NEH = new Point3D();
        /// <summary>
        /// Độ chuyển dịch hiện thời (Chu kỳ hiện thời so với chu kỳ trước
        /// </summary>
        public Point3D cur_dis = new Point3D();
        /// <summary>
        /// Danh sách độ dịch chuyển theo mặt bằng (Từ chu kỳ 0 đến chu kỳ hiện tại)
        /// </summary>
        public List<Point2D> list_hor_dis = new List<Point2D>();
        /// <summary>
        /// Danh sách độ dịch chuyển theo hướng Bắc (Từ chu kỳ 0 đến chu kỳ hiện tại)
        /// </summary>
        public List<Point2D> lis_time_dis_N = new List<Point2D>();
        /// <summary>
        /// Danh sách độ dịch chuyển theo hướng Đông (Từ chu kỳ 0 đến chu kỳ hiện tại)
        /// </summary>
        public List<Point2D> lis_time_dis_E = new List<Point2D>();
        /// <summary>
        /// Danh sách độ dịch chuyển theo độ cao (Từ chu kỳ 0 đến chu kỳ hiện tại)
        /// </summary>
        public List<Point2D> lis_time_dis_H = new List<Point2D>();

        //public List<Time_trans> lis_time = new List<Time_trans>();
        /// <summary>
        /// thong tin ve diem bao cao
        /// </summary>
        public String infor = "";

        public List<String> lis_infor = new List<String>();

        [XmlIgnore]
        public bool ini_chart = false;
        /// <summary>
        /// Cập nhật dữ liệu dạng Repoint từ kết quả bình sai
        /// </summary>
        /// <param name="i"></param>
        /// <param name="point"></param>
        /// <param name="round"></param>
        /// <param name="time"></param>
               
       public static RePoint read_from_file(string filename)
        {
            RePoint repoint = new RePoint();
            XmlSerializer xs = new XmlSerializer(typeof(RePoint));
            using (StreamReader rd = new StreamReader(filename))
            {
                repoint = (RePoint)xs.Deserialize(rd);
                rd.Close();
            }
            return repoint;
        }
        public static void print_to_file(string filename, RePoint repoint)
        {
            XmlSerializer xs = new XmlSerializer(typeof(RePoint));
            using (StreamWriter wr = new StreamWriter(filename))
            {
                xs.Serialize(wr, repoint);
                wr.Close();
            }
        }

    }
    public class motime
    {
       public int year=0;
       public int month=0;
       public int day=0;
       public int hour=0;
       public int minute=0;
       public double second=0;
       public int week=0;
       public double wsecond=0;
    }

    public class rtk_meas
    {
        public int receiverID = 0;
        public double GPStime = 0;
        public double GPSweek = 0;
        public double dN = 0;
        public double dE = 0;
        public double dU = 0;
        public double aN = 0;//GPS stdN
        public double aE = 0;//GPS stdE
        public double aU = 0;//GPS stdU
        public double heading = 0;
        public double dheading = 0;
        public double gspeed = 0;
        public int baseID = 0;
        public int rtk_status = 0;
        public Point3D BLH = new Point3D();
        public Point3D NEH = new Point3D();
        public Point3D preNEH = new Point3D();
        public Point3D std = new Point3D();
        public Point3D w = new Point3D();
        public Point3D W = new Point3D();
        public Point3D S = new Point3D();
        public int nstatic_update = 0;
        public bool data_come = false;
        public void update_weight()
        {
            this.w.X = 0.000001 / (aN * aN + 0.00000001);
            this.w.Y = 0.000001 / (aE * aE + 0.00000001);
            this.w.Z = 0.000001 / (aU * aU + 0.00000001);
        }


    }

    public class mopoint
    {
        public bool converted=false;
        public bool processed = false;
        public int fromorto=-1;
        public double coef=0;
        public string name="";
        public string basename="";
        public string obsname="";
        public string navname="";
        public string datafile="";
        public string resultfile="";
        public string pathname = "";
        public Point3D Appneu=new Point3D();// Approximated NEU
        public Point3D Adjneu = new Point3D();// Adjusted NEU
        public Point3D AppXYH = new Point3D();
        public Point3D llh = new Point3D();
       // public PointLatLng gmapll { get; set; }
        public Point3D std = new Point3D();
        public Point3D iniNEU = new Point3D();// Approximated NEU
        public Point3D iniNEU_std = new Point3D();
        public bool iniNEU_flag = false;
        public string[] pos_str = new string[3];
        public double[] antenna = new double[3];
        public int pos_opt = 0;
        public double ratio=0.0;
        public double displacement=0.0;
        public List<Point3D> listneu;
        public Time_trans startime=new Time_trans();
        public Time_trans endtime=new Time_trans();
        public int waiting_time = 10;
        public int rtk_mode = 0;//0: monitoring point; 1: rtk_point; 2: rtk_base
        public int rtk_base_id = 0;

        public double ax=0;
        public double by = 0;

        //GMap.NET.Placemark placemark=new GMap.NET.Placemark();
        public int id=0;
        public bool fix = false;
        public rtk_meas rtkmeas;
        public RePoint morepoint = new RePoint();
        public int nupdate = 0;
        public bool repoint_update_status = false;
        public bool ini_Imarker = false;
        public int receiverID = 40001;
        public System.IO.StringWriter tmp_String = new StringWriter();
        public System.IO.StreamWriter outfile;
        public bool map_display = false;
    
        

        public static mopoint getinfor(String filename)
        {
            String exePath = System.Windows.Forms.Application.StartupPath;
            mopoint point = new mopoint();
            point.datafile = filename;
            if (File.Exists(filename) == false)
            {
                point.waiting_time = 10;
                return point;
            }
            String pathname = Path.GetDirectoryName(filename);
            point.pathname = pathname;
            point.basename = Path.GetFileNameWithoutExtension(filename);

            point.obsname = pathname +"\\"+ point.basename + ".obs";
            point.navname = pathname + "\\" + point.basename + ".nav";
            point.resultfile = pathname + "\\" + point.basename + ".pos";
                 
            return point;
        }

        public void convert2rinex()
        {
            String exePath = System.Windows.Forms.Application.StartupPath;
            String convbin = exePath + "\\convbin.exe";
            String conarg = "-v " + "2.11" + " -r rtcm3" + " -o " + obsname + " -n " + navname + " " + datafile;
            //if (datafile.Contains("ubx"))
            //{
            //    conarg = "-v " + "2.11" + " -r ubx" + " -o " + obsname + " -n " + navname + " " + datafile;
            //}
            

            Process p = new Process();
            p.StartInfo.FileName = convbin;
            p.StartInfo.Arguments = conarg;
            p.EnableRaisingEvents = true;
            //p.StartInfo.Verb = "runas";
            //p.StartInfo.WindowStyle = ProcessWindowStyle.Hidden;
            try
            {

                p.Start();
                p.WaitForExit();
                p.Close();
                converted = true;


            }
            catch (Exception)
            {
                //System.Windows.Forms.MessageBox.Show("Something wrong in data convertion!");
                return;
            }
            

        }

        public static Double str_dms2deg(String dms)
					{
					double deg;
					double dd,mm,ss;
					Char[] delimiter = {' ','\t'};
			        String[] split = dms.Split(delimiter,StringSplitOptions.RemoveEmptyEntries);
            
					if(Double.TryParse(split[0],out dd)&&Double.TryParse(split[1],out mm)&&Double.TryParse(split[2],out ss))
					{
					 deg=dd+mm/60.0+ss/3600.0;
					 return deg*Math.PI/180.0;
					}
					else return -9999;
	               }
        public static int get_AppXYH_fromRNX_header(mopoint mpoint, C_Datum datum)
        {
            int get = 0;
            if (File.Exists(mpoint.obsname)==false) return 0;
            //else
            {

                System.IO.StreamReader infile = new System.IO.StreamReader(mpoint.obsname);
                if (infile == null)
                {
                    MessageBox.Show(" No output file, Please input one");

                }
                else
                {
                    string line;
                    char[] delidot = new char[] { ' ', '\t' };
                    while ((line = infile.ReadLine()) != null)
                    {
                        if (line.Contains("APPROX POSITION XYZ"))
                        {
                            
                            string[] data = line.Split(delidot, StringSplitOptions.RemoveEmptyEntries);
                            Double X, Y, Z;
                            if (Double.TryParse(data[0], out X) && Double.TryParse(data[1], out Y) && Double.TryParse(data[2], out Z) && X != 0 && Y != 0 && Z != 0)
                            {
                                mpoint.AppXYH.X = X;
                                mpoint.AppXYH.Y = Y;
                                mpoint.AppXYH.Z = Z;
                               // Point3D testp= BL2xy.XYZ2vn2000(RTMonitoring.rtmpopt.L0, RTMonitoring.rtmpopt.k0, mpoint.AppXYH);
                                mpoint.Appneu = BL2xy.XYZ2NEH(datum, mpoint.AppXYH);
                                mpoint.processed = true;
                                get = 1;
                            }

                        }
                        else continue;
                    }
                    infile.Close();
                }
            }

           return get;

        }

        public static int get_time_fromRNX_header(mopoint mpoint)
        {
            int get = 0;
            //if (mpoint.converted == false) return 0;
            //else
            {

                System.IO.StreamReader infile = new System.IO.StreamReader(mpoint.obsname);
                if (infile == null)
                {
                    MessageBox.Show(" No output file, Please input one");

                }
                else
                {
                    string line;
                    char[] delidot = new char[] { ' ', '\t' };
                    while ((line = infile.ReadLine()) != null)
                    {
                        if (line.Contains("TIME OF FIRST OBS"))
                        {

                            string[] data = line.Split(delidot, StringSplitOptions.RemoveEmptyEntries);
                            Double year, mon, day, hour, min;
                            double sec;
                            if (Double.TryParse(data[0], out year) && Double.TryParse(data[1], out mon) && Double.TryParse(data[2], out day) && Double.TryParse(data[3], out hour) && Double.TryParse(data[4], out min) && Double.TryParse(data[5], out sec) && year != 0 && mon != 0 && day != 0)
                            {
                                mpoint.startime.year = year;
                                mpoint.startime.month = mon;
                                mpoint.startime.day = day;
                                mpoint.startime.hh = hour;
                                mpoint.startime.mm = min;
                                mpoint.startime.ss = sec;
                                mpoint.startime.utc2gpst(year, mon, day, hour, min, sec);
                                mpoint.startime.timestring = mpoint.startime.year.ToString() + "/" + mpoint.startime.month.ToString() + "/" + mpoint.startime.day.ToString() + "\n" + mpoint.startime.hh.ToString() + ":" + mpoint.startime.mm.ToString() + ":" + mpoint.startime.ss.ToString();
                                //mpoint.Appneu = BL2xy.XYZ2NEH(mainForm.globalvar.G_current_datum, mpoint.AppXYH);
                                //mpoint.processed = true;
                                //get = 1;
                            }

                        }
                        else if (line.Contains("TIME OF LAST OBS"))
                        {

                            string[] data = line.Split(delidot, StringSplitOptions.RemoveEmptyEntries);
                            Double year, mon, day, hour, min;
                            double sec;
                            if (Double.TryParse(data[0], out year) && Double.TryParse(data[1], out mon) && Double.TryParse(data[2], out day) && Double.TryParse(data[3], out hour) && Double.TryParse(data[4], out min) && Double.TryParse(data[5], out sec) && year != 0 && mon != 0 && day != 0)
                            {
                                mpoint.endtime.year = year;
                                mpoint.endtime.month = mon;
                                mpoint.endtime.day = day;
                                mpoint.endtime.hh = hour;
                                mpoint.endtime.mm = min;
                                mpoint.endtime.ss = sec;
                                mpoint.endtime.utc2gpst(year, mon, day, hour, min, sec);
                                mpoint.endtime.timestring = mpoint.endtime.year.ToString() + "/" + mpoint.endtime.month.ToString() + "/" + mpoint.endtime.day.ToString() + "\n" + mpoint.endtime.hh.ToString() + ":" + mpoint.endtime.mm.ToString() + ":" + mpoint.endtime.ss.ToString();
                                //mpoint.Appneu = BL2xy.XYZ2NEH(mainForm.globalvar.G_current_datum, mpoint.AppXYH);
                                //mpoint.processed = true;
                                //get = 1;
                            }

                        }
                        else continue;
                    }
                    infile.Close();
                }
            }

            return get;

        }

        public static int get_AppXYH_fromSpp(mopoint mpoint, C_Datum datum)
        {
            int get = 0;
            int spp_processed = 0;
            if (mpoint.converted == false) return 0;
            else
            {
                String exePath = System.Windows.Forms.Application.StartupPath;
                String convbin = exePath + "\\aipos.exe";
                //String conarg = "-v " + "3.00" + " -r ubx" + " -o " + point.obsname + " -n " + point.navname + " " + point.datafile;
                String arg = " -p 0 " + "-o " + mpoint.resultfile + " " + mpoint.obsname + " " + mpoint.navname;
                Process p = new Process();
                p.StartInfo.FileName = convbin;
    
                p.StartInfo.Arguments = arg;
                p.EnableRaisingEvents = true;
               
                //p.ProcessName = "SPP processing";
                try
                {

                    //Process.Start(convbin, conarg);
                    p.Start();
                    p.WaitForExit();
                    p.Close();
                    spp_processed = 1;

                }
                catch (Exception)
                {
                    System.Windows.Forms.MessageBox.Show("Something wrong in geting point by SPP!");
                }

                if (spp_processed == 1)
                {
                    System.IO.StreamReader infile = new System.IO.StreamReader(mpoint.resultfile);
                    if (infile == null)
                    {
                        MessageBox.Show(" No output file, Please input one");

                    }
                    else
                    {
                        string line;
                        char[] delidot = new char[] { ' ', '\t' };
                        int nupdate=0;
                        
                        while ((line = infile.ReadLine()) != null)
                        {
                            if (line != "")
                            {
                                string[] data = line.Split(delidot, StringSplitOptions.RemoveEmptyEntries);
                                if (data[0] == "%") continue;
                                else if (data.Length > 10)
                                {
                                    string date = data[0];
                                    string time = data[1];
                                    double lat = Convert.ToDouble(data[2], CultureInfo.GetCultureInfo("en-US"));
                                    double lon = Convert.ToDouble(data[3], CultureInfo.GetCultureInfo("en-US"));
                                    double H = Convert.ToDouble(data[4], CultureInfo.GetCultureInfo("en-US"));
                                    if (nupdate == 0)
                                    {
                                        mpoint.llh.X = Convert.ToDouble(data[2], CultureInfo.GetCultureInfo("en-US"));
                                        mpoint.llh.Y = Convert.ToDouble(data[3], CultureInfo.GetCultureInfo("en-US"));
                                        mpoint.llh.Y = Convert.ToDouble(data[4], CultureInfo.GetCultureInfo("en-US"));
                                        nupdate++;
                                    }
                                    else
                                    {
                                   
                                        mpoint.llh.X = mpoint.llh.X + (lat - mpoint.llh.X) / nupdate;
                                        mpoint.llh.Y = mpoint.llh.Y + (lon - mpoint.llh.Y) / nupdate;
                                        mpoint.llh.Z = mpoint.llh.Z + (H - mpoint.llh.Z) / nupdate;
                                        nupdate++;     
                                    }
                                        
                                    
                                }
                            }
                        }
                        if (nupdate > 0)
                        {
                            Point3D llhrad = new Point3D();
                            llhrad.X = mpoint.llh.X * Math.PI / 180.0;
                            llhrad.Y = mpoint.llh.Y * Math.PI / 180.0;
                            llhrad.Z = mpoint.llh.Z * Math.PI / 180.0;
                            //mpoint.Appneu = BL2xy.llh2vn2000(RTMonitoring.rtmpopt.L0, RTMonitoring.rtmpopt.k0, llhrad);
                            mpoint.Appneu = BL2xy.llh2NEH(datum, llhrad);
                            get = 1;
                        }
                        infile.Close();
                    }
                }
            }

            return get;

        }

    }

    public class mobaseline
    {
        int index=0;
        public int processed = -1;//-1: not processed; 0: processed but no result; 1 processed with result 
        public bool passed = false;
        public mopoint frompoint;
        public mopoint topoint;
        public double length=0;
        public Point3D dneu=new Point3D();
        public Point3D dXYH=new Point3D();
        public Point3D std=new Point3D();
        public double hstd = 0;
        public double vstd = 0;
        public double ratio=0;
        public double displacement=0;
        public mopoint[] vector=new mopoint[2];
        public string resultfile = "";
        public string bresultfile = "";
        public Point3D refposllh = new Point3D();
        public Point3D refposNEH = new Point3D();
        public Point3D posllh = new Point3D();
        public Point3D posNEH = new Point3D();

        public bool isSmartbase = false;

        //[JsonIgnore]
        //public DateTime timePosstart;

        //[JsonIgnore]
        //public TcpListener listener { get; set; }
        //[JsonIgnore]
        //public Socket socket { get; set; }

        //[JsonIgnore]
        //public bool tcplistener { get; set; }

        //[JsonIgnore]
        //public bool isrtknavi_running { get; set; }

        //[JsonIgnore]
        //public TcpClient clientPos;
        //[JsonIgnore]
        //public bool isclientPos = false;

        //[JsonIgnore]
        //public System.IO.Stream streamPos;

        //[JsonIgnore]
        //public TcpClient clientDatum;
        //[JsonIgnore]
        //public bool isclientDatum = false;

        //[JsonIgnore]
        //public System.IO.Stream streamDatum;

        //[JsonIgnore]
        public Process p; 
        
        //[JsonIgnore]
        //public string posdata = "";

        //[JsonIgnore]
        //public bool rePositioning = false;//{ get; set; }

        //[JsonIgnore]
        public bool timetocalPos_opt = false;//{ get; set; }

        //[JsonIgnore]
        //public string timetocalPos = "00:00";//{ get; set; }

        //[JsonIgnore]
        public int mindurationcalPos = 60;//{ get; set; }

        public double minratiocalPos = 100;//{ get; set; }
        public double maxdistancePos = 30;//km

        public Point3D Basepos = new Point3D(); //{ get; set; }

        public int base_itrf = 2;

        public string ntrip_basepath = "aitogy:124@14.238.1.125:2101/VRS.105M3:";

        public bool storingData = true;//{ get; set; }

        public bool updatePos_opt = false;//{ get; set; }

        public double posupdate_threshold = 0.15;
        public string storingPath { get; set; }

        public bool TrackingOnWeb_opt = false;//{ get; set; }

        public bool isMQTT = false;//{ get; set; }
         

        //[JsonIgnore]
        public int ipr = 0;

        //[JsonIgnore]
        int curpos_status = 0;


        
        


        [DllImport("user32.dll", CharSet = CharSet.Auto)]
        private static extern bool SetForegroundWindow(IntPtr hWnd);
       public static int get_result(mobaseline baseline, double ratio_thres, C_Datum datum, rtmp_opt _Opt)
        {
            int processed = 0;
            
            System.IO.StreamReader infile = new System.IO.StreamReader(baseline.resultfile);
            if (infile == null)
            {
                MessageBox.Show(" No output file, Please input one");
               
            }
            else
            {
                string line;
                //line = infile.ReadLine();
                char[] delidot = new char[] { ' ','\t' };
                while ((line = infile.ReadLine()) != null)
                {
                    if (line != "")
                    {
                       
                        if (line.Contains("ref pos") == true)
                        {
                            string[] srefpos = line.Split(delidot, StringSplitOptions.RemoveEmptyEntries);
                            baseline.refposllh.X = Convert.ToDouble(srefpos[4], CultureInfo.GetCultureInfo("en-US")) * Math.PI / 180.0;
                            baseline.refposllh.Y = Convert.ToDouble(srefpos[5], CultureInfo.GetCultureInfo("en-US")) * Math.PI / 180.0;
                            baseline.refposllh.Z = Convert.ToDouble(srefpos[6], CultureInfo.GetCultureInfo("en-US"));
                            baseline.refposNEH = BL2xy.llh2NEH(datum, baseline.refposllh);
                        }
                        //else
                        //{
                            string[] data = line.Split(delidot, StringSplitOptions.RemoveEmptyEntries);
                            //if (data[0] == "%") continue;
                            if (data[0] != "%" && data.Length > 10)
                            {
                                //%  GPST                e-baseline(m)  n-baseline(m)  u-baseline(m)   Q  ns   sde(m)   sdn(m)   sdu(m)  sden(m)  sdnu(m)  sdue(m) age(s)  ratio
                                //2018/03/21 01:39:45.000        -1.5309        98.6433         5.6093   1   8   0.0003   0.0003   0.0007  -0.0001   0.0001   0.0001   0.00   15.4
                                
                                string date = data[0];
                                string time = data[1];
                            baseline.posllh.X = Convert.ToDouble(data[2], CultureInfo.GetCultureInfo("en-US")) * Math.PI / 180.0;
                            baseline.posllh.Y = Convert.ToDouble(data[3], CultureInfo.GetCultureInfo("en-US")) * Math.PI / 180.0;
                            baseline.posllh.Z = Convert.ToDouble(data[4], CultureInfo.GetCultureInfo("en-US"));
                            baseline.posNEH = BL2xy.llh2NEH(datum, baseline.posllh);
                            baseline.dneu.X = baseline.posNEH.X - baseline.refposNEH.X;
                            baseline.dneu.Y = baseline.posNEH.Y - baseline.refposNEH.Y;
                            baseline.dneu.Z = baseline.posNEH.Z - baseline.refposNEH.Z;

                            //baseline.dneu.X = Convert.ToDouble(data[3]);
                            //baseline.dneu.Y = Convert.ToDouble(data[2]);
                            //baseline.dneu.Z = Convert.ToDouble(data[4]);



                            baseline.length = Math.Sqrt(baseline.dneu.X * baseline.dneu.X + baseline.dneu.Y * baseline.dneu.Y + baseline.dneu.Z * baseline.dneu.Z);
                                baseline.std.X = Convert.ToDouble(data[8], CultureInfo.GetCultureInfo("en-US"));
                                baseline.std.Y = Convert.ToDouble(data[7], CultureInfo.GetCultureInfo("en-US"));
                                baseline.std.Z = Convert.ToDouble(data[9], CultureInfo.GetCultureInfo("en-US"));
                                baseline.hstd = Math.Sqrt(baseline.std.X * baseline.std.X + baseline.std.Y * baseline.std.Y);

                                baseline.ratio = Convert.ToDouble(data[14], CultureInfo.GetCultureInfo("en-US"));
                                baseline.processed = 1;
                                processed = 1;

                            if (baseline.ratio >= ratio_thres)
                            {
                                _Opt.list_probaseline.Add(baseline);
                                baseline.passed = true;
                            }


                                if (baseline.vector[0].processed == true && baseline.vector[1].processed == false)
                                {
                                    baseline.vector[1].Appneu = Point3D.plus(baseline.vector[0].Appneu, baseline.dneu);
                                    baseline.vector[1].std = Point3D.plus_std(baseline.vector[0].std, baseline.std);
                                    baseline.vector[1].processed = true;
                                }
                                else if (baseline.vector[0].processed == false && baseline.vector[1].processed == true)
                                {
                                    baseline.vector[0].Appneu = Point3D.minus(baseline.vector[1].Appneu, baseline.dneu);
                                    baseline.vector[0].std = Point3D.plus_std(baseline.vector[1].std, baseline.std);
                                    baseline.vector[0].processed = true;
                                }
                                
                            }



                            //else baseline.processed = 0;
                        //}
                    }
                }
             
            }
            infile.Close();
            return processed;
        }

        public static int get_bresult(mobaseline baseline, double ratio_thres, C_Datum datum, rtmp_opt _Opt)
        {
            int processed = 0;

            System.IO.StreamReader infile = new System.IO.StreamReader(baseline.bresultfile);
            if (infile == null)
            {
                MessageBox.Show(" No output file, Please input one");

            }
            else
            {
                string line;
                //line = infile.ReadLine();
                char[] delidot = new char[] { ' ', '\t' };
                while ((line = infile.ReadLine()) != null)
                {
                    if (line != "")
                    {

                        if (line.Contains("ref pos") == true)
                        {
                            string[] srefpos = line.Split(delidot, StringSplitOptions.RemoveEmptyEntries);
                            baseline.refposllh.X = Convert.ToDouble(srefpos[4], CultureInfo.GetCultureInfo("en-US")) * Math.PI / 180.0;
                            baseline.refposllh.Y = Convert.ToDouble(srefpos[5], CultureInfo.GetCultureInfo("en-US")) * Math.PI / 180.0;
                            baseline.refposllh.Z = Convert.ToDouble(srefpos[6], CultureInfo.GetCultureInfo("en-US"));
                            baseline.refposNEH = BL2xy.llh2NEH(datum, baseline.refposllh);
                        }
                        //else
                        //{

                            string[] data = line.Split(delidot, StringSplitOptions.RemoveEmptyEntries);
                            //if (data[0] == "%") continue;
                            if (data[0] != "%" && data.Length > 10)
                            {
                                //%  GPST                e-baseline(m)  n-baseline(m)  u-baseline(m)   Q  ns   sde(m)   sdn(m)   sdu(m)  sden(m)  sdnu(m)  sdue(m) age(s)  ratio
                                //2018/03/21 01:39:45.000        -1.5309        98.6433         5.6093   1   8   0.0003   0.0003   0.0007  -0.0001   0.0001   0.0001   0.00   15.4
                                string date = data[0];
                                string time = data[1];
                                if (baseline.processed < 1)
                                {

                                baseline.posllh.X = Convert.ToDouble(data[2], CultureInfo.GetCultureInfo("en-US")) * Math.PI / 180.0;
                                baseline.posllh.Y = Convert.ToDouble(data[3], CultureInfo.GetCultureInfo("en-US")) * Math.PI / 180.0;
                                baseline.posllh.Z = Convert.ToDouble(data[4], CultureInfo.GetCultureInfo("en-US"));
                                baseline.posNEH = BL2xy.llh2NEH(datum, baseline.posllh);
                                baseline.dneu.X = baseline.refposNEH.X - baseline.posNEH.X;
                                baseline.dneu.Y = baseline.refposNEH.Y - baseline.posNEH.Y;
                                baseline.dneu.Z = baseline.refposNEH.Z - baseline.posNEH.Z;
                                //baseline.dneu.X = -Convert.ToDouble(data[3]);
                                //baseline.dneu.Y = -Convert.ToDouble(data[2]);
                                //baseline.dneu.Z = -Convert.ToDouble(data[4]);
                                baseline.length = Math.Sqrt(baseline.dneu.X * baseline.dneu.X + baseline.dneu.Y * baseline.dneu.Y + baseline.dneu.Z * baseline.dneu.Z);
                                    baseline.std.X = Convert.ToDouble(data[8], CultureInfo.GetCultureInfo("en-US"));
                                    baseline.std.Y = Convert.ToDouble(data[7], CultureInfo.GetCultureInfo("en-US"));
                                    baseline.std.Z = Convert.ToDouble(data[9], CultureInfo.GetCultureInfo("en-US"));
                                    baseline.hstd = Math.Sqrt(baseline.std.X * baseline.std.X + baseline.std.Y * baseline.std.Y);
                                    baseline.ratio = Convert.ToDouble(data[14], CultureInfo.GetCultureInfo("en-US"));
                                    baseline.processed = 1;
                                    processed = 1;
                                    _Opt.list_probaseline.Add(baseline);
                                }
                                else
                                {
                                    baseline.posllh.X = Convert.ToDouble(data[2], CultureInfo.GetCultureInfo("en-US")) * Math.PI / 180.0;
                                    baseline.posllh.Y = Convert.ToDouble(data[3], CultureInfo.GetCultureInfo("en-US")) * Math.PI / 180.0;
                                    baseline.posllh.Z = Convert.ToDouble(data[4], CultureInfo.GetCultureInfo("en-US"));
                                    baseline.posNEH = BL2xy.llh2NEH(datum, baseline.posllh);
                                    Point3D bneu = new Point3D();
                                    bneu.X = baseline.posNEH.X - baseline.refposNEH.X;
                                    bneu.Y = baseline.posNEH.Y - baseline.refposNEH.Y;
                                    bneu.Z = baseline.posNEH.Z - baseline.refposNEH.Z;

                                    double br = Convert.ToDouble(data[14], CultureInfo.GetCultureInfo("en-US"));
                                    double fr = baseline.ratio;
                                    baseline.ratio = (baseline.ratio + br);
                                    baseline.dneu.X = (fr * baseline.dneu.X - br * bneu.X) / baseline.ratio;
                                    baseline.dneu.Y = (fr * baseline.dneu.Y - br * bneu.Y) / baseline.ratio;
                                    baseline.dneu.Z = (fr * baseline.dneu.Z - br * bneu.Z) / baseline.ratio;
                                    double length = Math.Sqrt(baseline.dneu.X * baseline.dneu.X + baseline.dneu.Y * baseline.dneu.Y + baseline.dneu.Z * baseline.dneu.Z);
                                    baseline.length = (fr * baseline.length + br * length) / baseline.ratio;
                                    baseline.std.X = (fr * baseline.std.X + br * Convert.ToDouble(data[8], CultureInfo.GetCultureInfo("en-US"))) / baseline.ratio;
                                    baseline.std.Y = (fr * baseline.std.Y + br * Convert.ToDouble(data[7], CultureInfo.GetCultureInfo("en-US"))) / baseline.ratio;
                                    baseline.std.Z = (fr * baseline.std.Z + br * Convert.ToDouble(data[9], CultureInfo.GetCultureInfo("en-US"))) / baseline.ratio;
                                    baseline.hstd = Math.Sqrt(baseline.std.X * baseline.std.X + baseline.std.Y * baseline.std.Y);
                                    //baseline.processed = 1;
                                    //processed = 1;
                                }

                                if (baseline.ratio >= ratio_thres) baseline.passed = true;


                                if (baseline.vector[0].processed == true && baseline.vector[1].processed == false)
                                {
                                    baseline.vector[1].Appneu = Point3D.plus(baseline.vector[0].Appneu, baseline.dneu);
                                    baseline.vector[1].std = Point3D.plus_std(baseline.vector[0].std, baseline.std);
                                    baseline.vector[1].processed = true;
                                }
                                else if (baseline.vector[0].processed == false && baseline.vector[1].processed == true)
                                {
                                    baseline.vector[0].Appneu = Point3D.minus(baseline.vector[1].Appneu, baseline.dneu);
                                    baseline.vector[0].std = Point3D.plus_std(baseline.vector[1].std, baseline.std);
                                    baseline.vector[0].processed = true;
                                }

                            }
                            //else baseline.processed = 0;
                        //}
                    }
                }

            }
            infile.Close();
            return processed;
        }
        public static void get_resultfile(mobaseline baseline)
        {
            //String resultfile = baseline.vector[0].pathname + "\\" + baseline.vector[0].basename + "_" + baseline.vector[1].basename+".vec";
            baseline.resultfile = baseline.vector[0].pathname + "\\" + baseline.vector[0].basename + "_" + baseline.vector[1].basename + ".vec";
            baseline.bresultfile = baseline.vector[0].pathname + "\\" + baseline.vector[1].basename + "_" + baseline.vector[0].basename + ".vec";
            //return resultfile;

        }
        public static int search_point(mopoint point, mobaseline baseline)
        {
            int found_point = 0;
            if (point == baseline.frompoint || point == baseline.topoint)
            {
                if (point == baseline.frompoint)
                {
                    //found_point = baseline.frompoint;
                    found_point = -1;
                }
                else if (point == baseline.topoint)
                {
                    //found_point = baseline.topoint;
                    found_point = 1;
                }
            }
            return found_point;

        }

        public static mopoint search_mopoint(mopoint point, mobaseline baseline)
        {
            mopoint found_point = null;
            if (point == baseline.frompoint || point == baseline.topoint)
            {
                if (point == baseline.frompoint)
                {
                    found_point = baseline.frompoint;
                    found_point.fromorto = -1;
                }
                else if (point == baseline.topoint)
                {
                    found_point = baseline.topoint;
                    found_point.fromorto = 1;
                }
            }
            return found_point;

        }
    }

    public class moloop
    {
        public bool processed = false;
        public bool passed = false;
        public List<mopoint> listmopoint=new List<mopoint>();
        public List<mobaseline> listmobaseline=new List<mobaseline>();
        public double length=0;
        public Point3D deltaneu=new Point3D();
        public Point3D fneu = new Point3D();
        public double fs=-1.0;
        public double ppm=0;

        public static void cal_loop(moloop loop)
        {
            int j;
            for (int i = 0; i < loop.listmopoint.Count; i++)
            {
                //for (int j = i + 1; j < loop.listmopoint.Count; j++)
                //{
                if (i == loop.listmopoint.Count-1) j = 0;
                else j = i+1;
                    for (int k = 0; k < loop.listmobaseline.Count; k++)
                    {
                        if (loop.listmobaseline[k].vector[0] == loop.listmopoint[i] && loop.listmobaseline[k].vector[1] == loop.listmopoint[j])
                        {
                            loop.fneu = Point3D.plus(loop.fneu, loop.listmobaseline[k].dneu);
                            //j = loop.listmopoint.Count;
                            break;
                        }
                        else if (loop.listmobaseline[k].vector[1] == loop.listmopoint[i] && loop.listmobaseline[k].vector[0] == loop.listmopoint[j])
                        {
                            loop.fneu = Point3D.minus(loop.fneu, loop.listmobaseline[k].dneu);
                            //j = loop.listmopoint.Count;
                            break;
                        }
                    }
                //}
            }
        }

        public static List<moloop> searchloop(List<mobaseline> listmobaseline)
        {
            int numloop = 0;
            List<moloop> list_moloop = new List<moloop>();
            for (int i = 0; i < listmobaseline.Count; i++)
            {
                for (int j = i+1; j < listmobaseline.Count; j++)
                {
                    int idfound1 = mobaseline.search_point(listmobaseline[i].vector[0], listmobaseline[j]);
                    if (idfound1 == -1)
                    {
                        for (int k = j+1; k < listmobaseline.Count; k++)
                        {
                            int idfound2 = mobaseline.search_point(listmobaseline[j].vector[1], listmobaseline[k]);
                            if (idfound2 == -1)
                            {
                                if (listmobaseline[k].vector[1] == listmobaseline[i].vector[1])
                                {
                                    numloop++;
                                    moloop newloop = new moloop();
                                    newloop.listmobaseline.Add(listmobaseline[i]);
                                    newloop.listmobaseline.Add(listmobaseline[j]);
                                    newloop.listmobaseline.Add(listmobaseline[k]);
                                    newloop.listmopoint.Add(listmobaseline[i].vector[0]);
                                    newloop.listmopoint.Add(listmobaseline[j].vector[1]);
                                    newloop.listmopoint.Add(listmobaseline[k].vector[1]);
                                    cal_loop(newloop);
                                    list_moloop.Add(newloop);
                                }
                            }
                            else if (idfound2 == 1)
                            {
                                if (listmobaseline[k].vector[0] == listmobaseline[i].vector[1])
                                {
                                    numloop++;
                                    moloop newloop = new moloop();
                                    newloop.listmobaseline.Add(listmobaseline[i]);
                                    newloop.listmobaseline.Add(listmobaseline[j]);
                                    newloop.listmobaseline.Add(listmobaseline[k]);
                                    newloop.listmopoint.Add(listmobaseline[i].vector[0]);
                                    newloop.listmopoint.Add(listmobaseline[j].vector[1]);
                                    newloop.listmopoint.Add(listmobaseline[k].vector[0]);
                                    cal_loop(newloop);
                                    list_moloop.Add(newloop);
                                }
                            }
                        }
                    }
                    else if (idfound1 == 1)
                    {
                        for (int k = j + 1; k < listmobaseline.Count; k++)
                        {
                            int idfound2 = mobaseline.search_point(listmobaseline[j].vector[0], listmobaseline[k]);
                            if (idfound2 == -1)
                            {
                                if (listmobaseline[k].vector[1] == listmobaseline[i].vector[1])
                                {
                                    numloop++;
                                    moloop newloop = new moloop();
                                    newloop.listmobaseline.Add(listmobaseline[i]);
                                    newloop.listmobaseline.Add(listmobaseline[j]);
                                    newloop.listmobaseline.Add(listmobaseline[k]);
                                    newloop.listmopoint.Add(listmobaseline[i].vector[0]);
                                    newloop.listmopoint.Add(listmobaseline[j].vector[0]);
                                    newloop.listmopoint.Add(listmobaseline[k].vector[1]);
                                    cal_loop(newloop);
                                    list_moloop.Add(newloop);
                                }
                            }
                            else if (idfound2 == 1)
                            {
                                if (listmobaseline[k].vector[0] == listmobaseline[i].vector[1])
                                {
                                    numloop++;
                                    moloop newloop = new moloop();
                                    newloop.listmobaseline.Add(listmobaseline[i]);
                                    newloop.listmobaseline.Add(listmobaseline[j]);
                                    newloop.listmobaseline.Add(listmobaseline[k]);
                                    newloop.listmopoint.Add(listmobaseline[i].vector[0]);
                                    newloop.listmopoint.Add(listmobaseline[j].vector[0]);
                                    newloop.listmopoint.Add(listmobaseline[k].vector[0]);
                                    cal_loop(newloop);
                                    list_moloop.Add(newloop);
                                }
                            }
                        }
                    }
                   
                }

            }
            return list_moloop;
        }




    }

}
