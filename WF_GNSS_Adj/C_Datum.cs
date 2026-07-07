using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Xml.Serialization;
using System.IO;
using System.Windows.Forms;

namespace WF_GNSS_Adj
{
    
    public class Ellip_Para// ini=WGS84
    {
        public double a = 6378137.0;
        public double b = 6356752.31424518;
        public double f = 1.0 / 298.2572236;
        public double we = 7.292115147e-5;
        public double e2 = 1 - Math.Pow((6356752.3142 / 6378137.0), 2);
        public double gm = 3986004.418e+8;
        public double j2 = 1.082626683e-3;
        public double j3 = -2.5327e-6;
    }

   
    public class C_Datum
    {
        /// <summary>
        /// Nhóm 1025////////////////
        /// </summary>
        public bool rtcm1025_update = false;
                /// <summary>
        /// Hệ số biến dạng chiều dài: toZone=3: k0=0.9999 ; toZone=6: k0=0.9996
        /// </summary>
        public double k0=0.9999;
        /// Kieu mui chieu( 3 do hay 6 do)
        /// </summary>
        public int ToZone = 3;//3 or 6 degree
        /// <summary>
        /// Thong so Elipsoid trai dat
        /// </summary>
        public double L0 = 105.0 * Math.PI / 180.0;
        /// <summary>
        /// Kinh tuyen truc phần độ
        /// </summary>
        public int Central_Meridian_Deg = 105;
        /// <summary>
        /// Kinh tuyen trục phần phút
        /// </summary>
        public int Central_Meridian_Min = 0;
     
                                     /// <summary>
/////////////////////////////////////////////////////////////////
        public Ellip_Para elip=new Ellip_Para();
        /// <summary>
        /// Kieu phep chieu: UTM hay Gauss
        /// </summary>
        public int ToProj = 0;//0: UTM; 1: Gauss
        /// <summary>
        /// Kieu Elipsoid (WGS-84 hay Karxopky
        /// </summary>
        public int ToEllip = 0;// 0: WGS-84;1: Kraxopky
        /// <summary>
        /// Kinh tuyen truc dang double
        /// </summary>
        //public List<String> CM_By_area=new List<string>();
        
        /// <summary>
        /// 7 tham số tính chuyển, bao gồm 3 tham số dịch chuyển, 3 tham số góc xoay và 1 tham số tỷ lệ
        /// </summary>
        /// Nhóm 1021
        public bool rtcm1021_update = false;

        public double kT = 0.999999747093722;
        public double dX = 191.90441429;
        public double dY = 39.30318279;
        public double dZ = 111.45032835;
        public double rX = 0.00928836;
        public double rY = -0.01975479;
        public double rZ = 0.00427372;
        //////////////////////////////end of 1021
        /// <summary>
        /// Kiểu mô hình tính chuyển (Busa-wolf hay Modensky)
        /// </summary>
        public int Para_Model=0;
        /// <summary>
        /// lệch đông của NEH 
        /// </summary>
        public double False_Easting=500000;
        /// <summary>
        /// Lệch Bắc của NEH
        /// </summary>
        public double False_Northing=0;
      
        /// Lệch Cao của NEH
        /// </summary>
        public double False_H = 0;

        /// <summary>
        /// Nhóm 1023///////////////
        /// </summary>
        public bool rtcm1023_update = false;
        public double resB = 0;
        public double resL=0; //Elipsoid residual in degree;
        public double resH=0; //Elipsoid residual in meter;
        ///
        public double resN=0;//North shift cors  //////////Change here 21/5/2020///////////
        public double resE=0;//East shift cors   //////////Change here 21/5/2020///////////
        public double resHS=0;//Height shift cors //////////Change here 21/5/2020///////////
        /// <summary>
        /// //////////////////////////end of 1023
        /// </summary>

        public int Tra_update;//0: defaul=vn-2000; 1: manual_input=interface; 2: auto from RTCM stream
        public bool Res_update;
        public bool Pro_update;
        public Point3D BasePosition;


        public bool ITRF = false;
        public bool rtcmBase_update = false;

        public bool shift_cors=true;
	
        /// <summary>
        /// Tên hệ tọa độ
        /// </summary>
        public String Name="WGS-84";
        [XmlIgnore]
        public String filename = "WGS-84";
        public int index = 0;
        public bool isdefault = false;
        public int datum_type = 0; //0:NEH, 1:BLH, 2:XYZ
        public int LAN = 1; //0:Vietnamese; 1:English ; 2: Chinese 

        public static void save_listdatum_to_file(String filename, List<C_Datum> listdatum)
        {
            XmlSerializer xs = new XmlSerializer(typeof(List<C_Datum>));
            using (StreamWriter wr = new StreamWriter(filename))
            {
                //xs.Serialize(wr, Globalvar.G_list_datum);
                wr.Close();
            }
        }
        public static List<C_Datum> read_listdatum_from_file(string filename)
        {
            
            //List<ParkingPlace> parkingplaces = new List<ParkingPlace>();
            List<C_Datum> listdatum = new List<C_Datum>();
            XmlSerializer xs = new XmlSerializer(typeof(List<C_Datum>));
            using (StreamReader rd = new StreamReader(filename))
            {
                listdatum = (List<C_Datum>)xs.Deserialize(rd);
                //datum.filename = filename;
                rd.Close();
            }
            return listdatum;
        
        }


        public static void save_datum_to_file(String filename, C_Datum datum)
        {
            XmlSerializer xs = new XmlSerializer(typeof(C_Datum));
            using (StreamWriter wr = new StreamWriter(filename))
            {
                xs.Serialize(wr, datum);
                wr.Close();
            }
        }
        public static C_Datum read_datum_from_file(string filename)
        {

            //List<ParkingPlace> parkingplaces = new List<ParkingPlace>();
            C_Datum datum = new C_Datum();
            XmlSerializer xs = new XmlSerializer(typeof(C_Datum));
            using (StreamReader rd = new StreamReader(filename))
            {
                datum = (C_Datum)xs.Deserialize(rd);
                datum.filename = filename;
                rd.Close();
            }
            return datum;

        }

      

        private static uint getbitu(byte[] buff, int pos, int len)
        {
            uint bits = 0;
            int i;
            for (i = pos; i < pos + len; i++)
            {
                bits = (uint)((bits << 1) + ((buff[i / 8] >> (7 - i % 8)) & 1u));
            }
            return bits;
        }

        private static int getbits(byte[] buff, int pos, int len)
        {
            uint bits = getbitu(buff, pos, len);
            if (len <= 0 || 32 <= len || (bits & (1u << (len - 1))) == 0)
            {
                return (int)bits;
            }
            return (int)(bits | (~0u << len)); // extend sign
        }

        private static double getbits_38(byte[] buff, int pos)
        {
            return (double)getbits(buff, pos, 32) * 64.0 + getbitu(buff, pos + 32, 6);
        }

        public void decode_type1021(byte[] buff, C_Datum datum)
        {
            char[] sn = new char[32];
            char[] tn = new char[32];
            int i = 36;
            //int i = 0;
            var n = (Decimal)(getbitu(buff, i, 5));
            var m = Convert.ToDecimal(getbitu(buff, i + 5 + 8 * (int)n, 5));
            if (i + 400 + 8 * n + 8 * m <= buff.Length * 8 + 24)
            {

                var snc = Convert.ToDecimal(getbitu(buff, i, 5)); i += 5;
                for (int j = 0; j < n && j < 31; j++)
                {
                    sn[j] = (char)getbitu(buff, i, 8); i += 8;
                }

                var tnc = Convert.ToDecimal(getbitu(buff, i, 5)); i += 5;
                for (int j = 0; j < m && j < 31; j++)
                {
                    tn[j] = (char)getbitu(buff, i, 8); i += 8;
                }

                var SIN = (Decimal)getbitu(buff, i, 8); i += 8;
                var UTMI = (Decimal)getbitu(buff, i, 10); i += 10;
                var PN = (Decimal)getbitu(buff, i, 5); i += 5;
                var CI = (Decimal)getbitu(buff, i, 4); i += 4;
                var HI = (Decimal)getbitu(buff, i, 2); i += 2;
                var LaO = (Decimal)getbits(buff, i, 19); i += 19;
                var LoO = (Decimal)getbits(buff, i, 20); i += 20;
                var NSE = (Decimal)getbitu(buff, i, 14); i += 14;
                var EWE = (Decimal)getbitu(buff, i, 14); i += 14;

                var dx = (Decimal)getbits(buff, i, 23); i += 23;
                var dy = (Decimal)getbits(buff, i, 23); i += 23;
                var dz = (Decimal)getbits(buff, i, 23); i += 23;
                var rx = (Decimal)getbits(buff, i, 32); i += 32;
                var ry = (Decimal)getbits(buff, i, 32); i += 32;
                var rz = (Decimal)getbits(buff, i, 32); i += 32;
                var ds = (Decimal)getbits(buff, i, 25); i += 25; //////////Change here 21/5/2020///////////
                datum.dX = (double)dx * 0.001;
                datum.dY = (double)dy * 0.001;
                datum.dZ = (double)dz * 0.001;
                datum.rX = (double)rx * 0.00002;
                datum.rY = (double)ry * 0.00002;
                datum.rZ = (double)rz * 0.00002;
                datum.kT = (double)ds * 0.00000000001 + 1;
                datum.Tra_update = 2;
                datum.rtcm1021_update = true;

            }

        }

        public void decode_type1023(byte[] buff, C_Datum datum)
        {
            // int MsgNum;
            // //char des[32] = "", sno[32] = "", rec[32] = "", ver[32] = "", rsn[32] = "";
            // //char* msg;
            int i = 24, j, n, m, n1, n2, n3, setup;
            // int Hsind, Vsind;
            // double LatOG, LonOG, NSE, EWS, MLatO, MLonO, MHO;
            //// 
            decimal[] latRes = new decimal[16], lonRes = new decimal[16], HeiRes = new decimal[16];
            double[] dlatRes = new double[16], dlonRes = new double[16], dHeiRes = new double[16];
            //HorIMI, VerIMI, HorGQI, VerGQI, MDJN;
            decimal[] glat = new decimal[16], glon = new decimal[16];
            double resB, resL, resH;
            var MsgNum = (Decimal)getbitu(buff, i, 12); i += 12;
            if (i + 566 <= buff.Length * 8 + 24)
            {
                var staid = (Decimal)getbitu(buff, i, 8); i += 8;
                var HorIMI = (Decimal)getbitu(buff, i, 1); i += 1;
                var VerIMI = (Decimal)getbitu(buff, i, 1); i += 1;
                var LatOG = (Decimal)getbits(buff, i, 21); i += 21;
                var LonOG = (Decimal)getbits(buff, i, 22); i += 22;
                var NSE = (Decimal)getbitu(buff, i, 12); i += 12;
                var EWS = (Decimal)getbitu(buff, i, 12); i += 12;
                var MLatO = (Decimal)getbits(buff, i, 8); i += 8;
                var MLonO = (Decimal)getbits(buff, i, 8); i += 8;
                var MHO = (Decimal)getbits(buff, i, 15); i += 15;


                for (j = 0; j < 16; j++)
                {
                    latRes[j] = (Decimal)getbits(buff, i, 9); i += 9;
                    dlatRes[j] = (double)latRes[j];
                    lonRes[j] = (Decimal)getbits(buff, i, 9); i += 9;
                    dlonRes[j] = (double)lonRes[j];
                    HeiRes[j] = (Decimal)getbits(buff, i, 9); i += 9;
                    dHeiRes[j] = (double)HeiRes[j];
                }
                double dMLatO = (double)MLatO;
                double dMLonO = (double)MLonO;
                double dMHO = (double)MHO;

                resB = dMLatO * 0.001 + (dlatRes[5] + dlatRes[6] + dlatRes[9] + dlatRes[10]) / 4 * 0.00003;//unit in second
                resL = dMLonO * 0.001 + (dlonRes[5] + dlonRes[6] + dlonRes[9] + dlonRes[10]) / 4 * 0.00003;//unit in second
                resH = dMHO * 0.01 + (dHeiRes[5] + dHeiRes[6] + dHeiRes[9] + dHeiRes[10]) / 4 * 0.001;//unit in meter

                datum.resB = resB * (Math.PI / (3600.0 * 180.0));      //unit in radian  //////////Change here 21/5/2020/////////// 
                datum.resL = resL * (Math.PI / (3600.0 * 180.0));      //unit in radian  //////////Change here 21/5/2020///////////
                datum.resH = resH = -resH;                             //unit in meter   //////////Change here 21/5/2020///////////
                datum.Tra_update = datum.Tra_update + 1;
                datum.Res_update = true;
                datum.rtcm1023_update = true;
            }
        }

        public void decode_type1025(byte[] buff, C_Datum datum)
        {

            int i = 24;
            //j, staid, n, m, n1, n2, n3, setup;
            var MsgNum = (Decimal)getbitu(buff, i, 12); i += 12;
            if (i + 184 <= buff.Length * 8 + 24)
            {
                var staid = (Decimal)getbitu(buff, i, 8); i += 8;
                var PT = (Decimal)getbitu(buff, i, 6); i += 6;
                var LaNO = (Decimal)getbits(buff, i, 34); i += 34;
                ////var LoNO = (Decimal)getbits(buff, i,35); //i += 35;
                var LoNO = getbits_38(buff, i); i += 35;
                var SNO = (Decimal)getbitu(buff, i, 30); i += 30;
                var FE = (Decimal)getbitu(buff, i, 36); i += 36;
                var FN = (Decimal)getbits(buff, i, 35);
                //rtcm->ctm.msg1025_update += 1;
                double dSNO = (double)SNO * 0.00001 + 993000;
                double dFE = (double)FE * 0.001;//False Easting
                double dFN = (double)FN * 0.001;// False Northing 
                dSNO = dSNO * 0.000001;
                double dLoNO = (double)LoNO * 0.000000011 / 8.0;

                datum.L0 = Math.Round(dLoNO, 6);
                datum.k0 = Math.Round(dSNO, 6);
                datum.False_Easting = dFE;
                datum.False_Northing = dFN;
                datum.rtcm1025_update = true;
            }
        }

        //static int decode_type1006(rtcm_t* rtcm)
        public Point3D decode_type1006(byte[] buff)
        {
            //var rr[3];//, anth;
            //char* msg;
            Point3D Basellh = new Point3D();
            int i = 24 + 12;//, j, staid, itrf;

            if (i + 156 <= buff.Length * 8 + 24)
            {
                var staid = (Decimal)getbitu(buff, i, 12); i += 12;
                var itrf = (Decimal)getbitu(buff, i, 6); i += 6 + 4;
                var rr0 = (Decimal)getbits_38(buff, i); i += 38 + 2;
                var rr1 = (Decimal)getbits_38(buff, i); i += 38 + 2;
                var rr2 = (Decimal)getbits_38(buff, i); i += 38;
                var anth = (Decimal)getbitu(buff, i, 16);

                Point3D XYZ = new Point3D();
                XYZ.X = (double)rr0 * 0.0001;
                XYZ.Y = (double)rr1 * 0.0001;
                XYZ.Z = (double)rr2 * 0.0001;
                Basellh = BL2xy.xyz2llh(XYZ);
                Basellh.Z = Basellh.Z - (double)anth * 0.0001;
               
            }

            return Basellh;

        }


        public static Point3D decode_type1005(byte[] buff)
        {
            Point3D Basellh = new Point3D();
            //double rr[3];
            //char* msg;
            //int i = 24 + 12, j, staid, itrf;
            int i = 24 + 12;//, j, staid, itrf;

            if (i + 140 <= buff.Length * 8 + 24)
            {
                var staid = (Decimal)getbitu(buff, i, 12); i += 12;
                var itrf = (Decimal)getbitu(buff, i, 6); i += 6 + 4;
                var rr0 = (Decimal)getbits_38(buff, i); i += 38 + 2;
                var rr1 = (Decimal)getbits_38(buff, i); i += 38 + 2;
                var rr2 = (Decimal)getbits_38(buff, i); i += 38;
                var anth = (Decimal)getbitu(buff, i, 16);
                Point3D XYZ = new Point3D();
                XYZ.X = (double)rr0 * 0.0001;
                XYZ.Y = (double)rr1 * 0.0001;
                XYZ.Z = (double)rr2 * 0.0001;
                Basellh = BL2xy.xyz2llh(XYZ);
                Basellh.Z = Basellh.Z - (double)anth * 0.0001;
               
            }
            return Basellh;

           
        }

        public void rOnIncomingRTCM(List<byte> lbuffer, C_Datum datum, out Point3D basepos)
        {
        
            basepos = new Point3D();
           
           
            if (lbuffer.Count < 6)
            {
                return;
            }

            if (lbuffer.Count >= ushort.MaxValue)
            {
                lbuffer.RemoveRange(0, ushort.MaxValue);
            }
            

            for (int id = 0; id < lbuffer.Count - 6 && id+4 < lbuffer.Count; id++)
            {

                if (lbuffer[id] == 0xD3 && lbuffer[id + 1] == 0x00 && lbuffer[id + 3] == 0x3F && (lbuffer[id + 4] & 0xF0) == 0xD0)
                {

                   
                    var PayloadLength = Convert.ToDecimal(lbuffer[id + 2]);

                    if (lbuffer.Count <= id + (int)PayloadLength)//1021:88; 1023:73; 1025:25; 1006:21
                    {
                        break;
                    }
                    else
                    {

                        
                        byte[] buff = new byte[(int)PayloadLength + 6]; //////// message buffer
                        int idx = id + 6;

                        for (int t = 0; t < (int)PayloadLength + 6 && id< lbuffer.Count; t++)
                        {
                            buff[t] = lbuffer[id];
                            id++;
                        }
                        var MsgNum = (Decimal)getbitu(buff, 24, 12);
                        decode_type1021(buff, datum);
                        lbuffer.Clear();
                        break;
                    }

                }

 
                if (lbuffer[id] == 0xD3 && lbuffer[id + 1] == 0x00 && lbuffer[id + 3] == 0x3F && (lbuffer[id + 4] & 0xF0) == 0xF0)
                {


                    var PayloadLength = Convert.ToDecimal(lbuffer[id + 2]);

                    if (lbuffer.Count <= id + (int)PayloadLength)//1021:88; 1023:73; 1025:25; 1006:21
                    {
                        break;
                    }
                    else
                    {


                        byte[] buff = new byte[(int)PayloadLength + 6]; //////// message buffer
                        int idx = id + 6;

                        for (int t = 0; t < (int)PayloadLength + 6 &&id < lbuffer.Count; t++)
                        {
                            buff[t] = lbuffer[id];
                            id++;
                        }
                        decode_type1023(buff, datum);

                        if (lbuffer.Count >= (int)PayloadLength)
                            lbuffer.RemoveRange(0, (int)PayloadLength);
                        //lbuffer.Clear();
                        break;
                    }

                }
                
                if (lbuffer[id] == 0xD3 && lbuffer[id + 1] == 0x00 && lbuffer[id + 3] == 0x40 && (lbuffer[id + 4] & 0xF0) == 0x10)
                
                {

                    var PayloadLength = Convert.ToDecimal(lbuffer[id + 2]);

                    if (lbuffer.Count <= id + (int)PayloadLength)//1021:88; 1023:73; 1025:25; 1006:21
                    {
                        break;
                    }
                    else
                    {


                        byte[] buff = new byte[(int)PayloadLength + 6]; //////// message buffer
                        int idx = id + 6;

                        for (int t = 0; t < (int)PayloadLength + 6 && id < lbuffer.Count; t++)
                        {
                            buff[t] = lbuffer[id];
                            id++;
                        }
                        decode_type1025(buff, datum);

                        if (lbuffer.Count >= (int)PayloadLength)
                            lbuffer.RemoveRange(0, (int)PayloadLength);
                        //lbuffer.Clear();
                        break;
                    }

                }

                else if (lbuffer[id] == 0xD3 && lbuffer[id + 1] == 0x00 && lbuffer[id + 3] == 0x3E && (lbuffer[id + 4] & 0xF0) == 0xE0)
                {

                    var PayloadLength = Convert.ToDecimal(lbuffer[id + 2]);

                    if (lbuffer.Count <= id + (int)PayloadLength)//1021:88; 1023:73; 1025:25; 1006:21
                    {
                        break;
                    }
                    else
                    {


                        byte[] buff = new byte[(int)PayloadLength + 6]; //////// message buffer
                        int idx = id + 6;

                        for (int t = 0; t < (int)PayloadLength + 6 && id < lbuffer.Count; t++)
                        {
                            buff[t] = lbuffer[id];
                            id++;
                        }
                        basepos = decode_type1006(buff);
                        if (lbuffer.Count >= (int)PayloadLength)
                            lbuffer.RemoveRange(0, (int)PayloadLength);
                        //lbuffer.Clear();
                        break;
                    }

                }

                else if (lbuffer[id] == 0xD3 && lbuffer[id + 1] == 0x00 && lbuffer[id + 3] == 0x3E && (lbuffer[id + 4] & 0xF0) == 0xD0)
                {
                    var PayloadLength = Convert.ToDecimal(lbuffer[id + 2]);

                    if (lbuffer.Count <= id + (int)PayloadLength)//1021:88; 1023:73; 1025:25; 1006:21
                    {
                        break;
                    }
                    else
                    {


                        byte[] buff = new byte[(int)PayloadLength + 6]; //////// message buffer
                        int idx = id + 6;

                        for (int t = 0; t < (int)PayloadLength + 6 && id < lbuffer.Count; t++)
                        {
                            buff[t] = lbuffer[id];
                            id++;
                        }
                        basepos = decode_type1005(buff);
                        if (lbuffer.Count >= (int)PayloadLength)
                            lbuffer.RemoveRange(0, (int)PayloadLength);
                        //lbuffer.Clear();
                        break;
                    }
                }

            }
        } ////public void rOnIncomingRTCM(string fileName)




    }
}
