using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Drawing;
//using CSML;
//using PointNav.RTM;
using System.Globalization;
using System.Runtime.Remoting.Messaging;
namespace WF_GNSS_Adj
{
    public class Pointll
    {
        private double lt, ln, r;
        public Pointll(double lt, double ln, double r) { this.lt = lt; this.ln = ln; this.r = r; }
        public double glt() { return lt; }
        public double gln() { return ln; }
        public double gr() { return r; }
    }

    public class Trilateration
    {
       public static double  distancePoints(double[] p1, double[] p2) 
       {
            // Find the distance between two points
            return Math.Sqrt(Math.Pow(p2[0] - p1[0], 2) + Math.Pow(p2[1] - p1[1], 2));
                   }

       public static List<double[]> intersectCircles(double[] c1, double r1, double[] c2, double r2) 
       {
            // Find the points of intersection for two circles
            // Based on: http://stackoverflow.com/a/3349134
            //double[][] result =pmatrix.MatrixCreate(2, 2);
            List<double[]> result = new List<double[]>();
            var d = distancePoints(c1, c2);
            if (d > r1 + r2) // Circles do not overlap
                return result;
            if (d < Math.Abs(r1 - r2)) // One circle contains the other
                return result;
            if (d == 0 && r1 == r2) // These are the same circle
                return result;

            // Find distances of dimensions from the first point
            var a = (Math.Pow(r1, 2) - Math.Pow(r2, 2) + Math.Pow(d, 2)) / (2 * d);
            var h = Math.Sqrt(Math.Pow(r1, 2) - Math.Pow(a, 2));

            // Determine point on the line between centers perpendicular to intersects
            var p = new double[2];
                p[0]= c1[0] + a * (c2[0] - c1[0]) / d;
                p[1]= c1[1] + a * (c2[1] - c1[1]) / d;
            

            // Calculate intersection points
                double[] p1 =  new double[2];
                double[] p2 =  new double[2];
                
                p1[0]=p[0] + h * (c2[1] - c1[1]) / d;
                p1[1]=p[1] - h * (c2[0] - c1[0]) / d;
                result.Add(p1);
                
                p2[0] = p[0] - h * (c2[1] - c1[1]) / d;
                p2[1] = p[1] + h * (c2[0] - c1[0]) / d;
                result.Add(p2);
                return result;       
            
        }


    
        public static double[] triangulate(double[] c1, double r1, double[]c2, double r2, double[]c3, double r3) 
        {


            double[] foundpoint = new double[2];
            // Triangulate with all combinations
            List<Point3D> points =new List<Point3D>(); 
        //    for (var i = 0; i < 3; i ++) {
               var crossPoints = intersectCircles(
                    c1, r1, c2, r2);
        
        //        var thirdPoint = circles[(i+2)%3];
               double[] offsets = new double[2];
               offsets[0] = Math.Abs(distancePoints(crossPoints[0], c3) - r3);
               offsets[1] = Math.Abs(distancePoints(crossPoints[1], c3) - r3);

        //    // Find the most precisely triangulated point
        //    var pointIndex = 0;
               if (offsets[0] < offsets[1]) foundpoint = crossPoints[0];
               else foundpoint = crossPoints[1];
                   return foundpoint; //points[pointIndex][0];
        }



        
        public static double[] Compute(Pointll p1, Pointll p2, Pointll p3)
        {
            double[] a = new double[3];
            double[] b = new double[3];
            double c, d, f, g, h;
            double[] i = new double[2];
            double k;
            c = p2.glt() - p1.glt();
            d = p2.gln() - p1.gln();
            f = (180 / Math.PI) * Math.Acos(Math.Abs(c) / Math.Abs(Math.Sqrt(Math.Pow(c, 2) + Math.Pow(d, 2))));
            if ((c > 0 && d > 0)) { f = 360 - f; }
            else if ((c < 0 && d > 0)) { f = 180 + f; }
            else if ((c < 0 && d < 0)) { f = 180 - f; }
            a = C(c, d, B(A(D(p2.gr()))), f);
            b = C(p3.glt() - p1.glt(), p3.gln() - p1.gln(), B(A(D(p3.gr()))), f);
            g = (Math.Pow(B(A(D(p1.gr()))), 2) - Math.Pow(a[2], 2) + Math.Pow(a[0], 2)) / (2 * a[0]);
            h = (Math.Pow(B(A(D(p1.gr()))), 2) - Math.Pow(b[2], 2) - Math.Pow(g, 2) + Math.Pow(g - b[0], 2) + Math.Pow(b[1], 2)) / (2 * b[1]);
            i = C(g, h, 0, -f);
            i[0] = i[0] + p1.glt() - 0.086;
            i[1] = i[1] + p1.gln() - 0.004;
            k = E(i[0], i[1], p1.glt(), p1.gln());
            if (k > p1.gr() * 2) { i = null; }
            else
            {
                if (i[0] < -90 || i[0] > 90 || i[1] < -180 || i[1] > 180) { i = null; }
            }
            return i;
        }
        private static double A(double a) { return a * 7.2; }
        private static double B(double a) { return a / 900000; }
        private static double[] C(double a, double b, double c, double d) { return new double[] { a * Math.Cos((Math.PI / 180) * d) - b * Math.Sin((Math.PI / 180) * d), a * Math.Sin((Math.PI / 180) * d) + b * Math.Cos((Math.PI / 180) * d), c }; }
        private static double D(double a) { return 730.24198315 + 52.33325511 * a + 1.35152407 * Math.Pow(a, 2) + 0.01481265 * Math.Pow(a, 3) + 0.00005900 * Math.Pow(a, 4) + 0.00541703 * 180; }
        private static double E(double a, double b, double c, double d) { double e = Math.PI, f = e * a / 180, g = e * c / 180, h = b - d, i = e * h / 180, j = Math.Sin(f) * Math.Sin(g) + Math.Cos(f) * Math.Cos(g) * Math.Cos(i); if (j > 1) { j = 1; } j = Math.Acos(j); j = j * 180 / e; j = j * 60 * 1.1515; j = j * 1.609344; return j; }
    }
    class dms
    {
        public int d = 0;
        public int m = 0;
        public double s = 0.0;
    }
    class WGS84
    {
        public static double a = 6378137.0;
        public static double b = 6356752.31424518;
        public static double e2 = 0.00669437999013;
    }
   
    class Kra
    {
        public static double a = 6378245.0;
        public static double b = 6356863.01877;
        public static double e2 = 0.006693421623;
    }

    class BL2xy
    {
        public static double xout;
        public static double yout;
        public static double Hout;
        public static double B;
        public static double L;
        public static int dB;
        public static int pB;
        public static double gB;
        public static int dL;
        public static int pL;
        public static double gL;

        public static int dd;
        public static int ppp;
        public static double gg;
    
        
        public static long max = 1000;
        //public static double kow = 0.9996;
        public static double ep2 = 0.00673949674227;
        //public static double esl = 0.00000000000001;
        public static double doi_dpg_ra(int d,int p,double g)
	    {
        double rad;
		double pi=4.0*Math.Atan(1.0);
        rad=((double)d+(double)p/60.0+g/3600.0)*pi/180.0;
		return rad;
	    }
		public static void doi_ra_dpg(double v)
	    {
	    double pp;
		double pi;
		pi=4.0*Math.Atan(1.0);
    	v=v*180.0/pi;
		BL2xy.dd=(int)v;
		pp=(v-dd)*60.0;
        BL2xy.ppp = (int)pp;
        BL2xy.gg = (pp - ppp) * 60.0;
	    }

        public dms rad2dms(double v)
        {
            dms _dms = new dms();
            double pp;
            double pi;
            pi = 4.0 * Math.Atan(1.0);
            v = v * 180.0 / pi;
            _dms.d = (int)v;
            pp = (v - dd) * 60.0;
            _dms.m = (int)pp;
            _dms.s = Math.Round(((pp - ppp) * 60.0),2);
            return _dms;
        }

        static double demise2rad(string dms)
        {
            double dmsD = Convert.ToDouble(dms, CultureInfo.GetCultureInfo("en-US"));
            int dd = (int)dmsD;
            Double mmd = (dmsD - dd) * 100;
            int mm = (int)(mmd);
            if (mm >= 60)
            {
                dd = dd + 1;
                mm = 0;
            }
            double ss = ((dmsD - dd) * 100.0 - mm) * 100.0;
            if (ss >= 60)
            {
                ss = 0.0;
                mm = mm + 1;
            }
            double degrad = ((double)dd + (double)mm / 60.0 + ss / 3600.0) * Math.PI / 180.0;
            return degrad;
        }
        public static void BLH2xy(double Lo, double a, double b, double e2, double kow, double B, double L, double H)
        {
            double l = L - Lo;
            double n2 = ep2 * Math.Cos(B) * Math.Cos(B);
            double t = Math.Tan(B);
            double N = a / Math.Sqrt(1.0 - e2 * Math.Sin(B) * Math.Sin(B));
            double mo = l * Math.Cos(B);
            double X = 6367449.1458 * B - 16038.5086 * Math.Sin(2.0 * B) + 16.8326 * Math.Sin(4.0 * B) - 0.0220 * Math.Sin(6.0 * B);
            double ct10 = (1.0 / 2.0) * N * t * mo * mo;
            double ct11 = (1.0 / 24.0) * N * t * (5.0 - t * t + 9.0 * n2 + 4.0 * n2 * n2) * Math.Pow(mo, 4);
            double ct12 = (1.0 / 720.0) * N * t * (61.0 - 58.0 * t * t + Math.Pow(t, 4) + 270.0 * n2 - 330.0 * n2 * t * t) * Math.Pow(mo, 6);

            double ct13 = N * mo;
            double ct14 = (1.0 / 6.0) * (1.0 - t * t + n2) * N * Math.Pow(mo, 3);
            double ct15 = (1.0 / 120.0) * (5.0 - 18.0 * t * t + Math.Pow(t, 4) + 14.0 * n2 - 58.0 * n2 * t * t) * N * Math.Pow(mo, 5);//?????


            double ct16 = t * mo;
            double ct17 = (1.0 / 3.0) * (1.0 + 3 * n2 + 2 * n2 * n2) * t * Math.Pow(mo, 3);
            double ct18 = (1.0 / 15.0) * (2.0 - t * t) * t * Math.Pow(mo, 5);

            double xG = X + ct10 + ct11 + ct12;
            double yG = ct13 + ct14 + ct15;
            double xUTM = xG * kow;
            double ypUTM = yG * kow;
            double yUTM = 500000.0 + ypUTM;
            double HUTM = ct16 + ct17 + ct18;

            xout = xUTM;
            yout = yUTM;
            Hout = HUTM;


        }

        public static PointF BL2xy_v2(double Lo,double B, double L)
        {
            PointF pointout = new PointF();
            double a = WGS_84.a;
            double e2 = WGS_84.e2;
            double b=WGS_84.b;
            //double  sta double kow6 = 0.9996;
            double kow = 0.9999;
            double l = L - Lo;
            double n2 = ep2 * Math.Cos(B) * Math.Cos(B);
            double t = Math.Tan(B);
            double N = a / Math.Sqrt(1.0 - e2 * Math.Sin(B) * Math.Sin(B));
            double mo = l * Math.Cos(B);
            double X = 6367449.1458 * B - 16038.5086 * Math.Sin(2.0 * B) + 16.8326 * Math.Sin(4.0 * B) - 0.0220 * Math.Sin(6.0 * B);
            double ct10 = (1.0 / 2.0) * N * t * mo * mo;
            double ct11 = (1.0 / 24.0) * N * t * (5.0 - t * t + 9.0 * n2 + 4.0 * n2 * n2) * Math.Pow(mo, 4);
            double ct12 = (1.0 / 720.0) * N * t * (61.0 - 58.0 * t * t + Math.Pow(t, 4) + 270.0 * n2 - 330.0 * n2 * t * t) * Math.Pow(mo, 6);

            double ct13 = N * mo;
            double ct14 = (1.0 / 6.0) * (1.0 - t * t + n2) * N * Math.Pow(mo, 3);
            double ct15 = (1.0 / 120.0) * (5.0 - 18.0 * t * t + Math.Pow(t, 4) + 14.0 * n2 - 58.0 * n2 * t * t) * N * Math.Pow(mo, 5);//?????


            double ct16 = t * mo;
            double ct17 = (1.0 / 3.0) * (1.0 + 3 * n2 + 2 * n2 * n2) * t * Math.Pow(mo, 3);
            double ct18 = (1.0 / 15.0) * (2.0 - t * t) * t * Math.Pow(mo, 5);

            double xG = X + ct10 + ct11 + ct12;
            double yG = ct13 + ct14 + ct15;
            double xUTM = xG * kow;
            double ypUTM = yG * kow;
            double yUTM = 500000.0 + ypUTM;
            double HUTM = ct16 + ct17 + ct18;

            xout = xUTM;
            yout = yUTM;
            //Hout = HUTM;
            pointout = new PointF((float)xout, (float)yout);
            return pointout;


        }

        public static Point3D BLH2xyh(double Lo, double k0, double B, double L, double H)
        {
            Point3D xyh = new Point3D();
            double a = WGS_84.a;
            double e2 = WGS_84.e2;
            double b = WGS_84.b;
            double kow = k0;
            double l = L - Lo;
            double n2 = ep2 * Math.Cos(B) * Math.Cos(B);
            double t = Math.Tan(B);
            double N = a / Math.Sqrt(1.0 - e2 * Math.Sin(B) * Math.Sin(B));
            double mo = l * Math.Cos(B);
            double X = 6367449.1458 * B - 16038.5086 * Math.Sin(2.0 * B) + 16.8326 * Math.Sin(4.0 * B) - 0.0220 * Math.Sin(6.0 * B);
            double ct10 = (1.0 / 2.0) * N * t * mo * mo;
            double ct11 = (1.0 / 24.0) * N * t * (5.0 - t * t + 9.0 * n2 + 4.0 * n2 * n2) * Math.Pow(mo, 4);
            double ct12 = (1.0 / 720.0) * N * t * (61.0 - 58.0 * t * t + Math.Pow(t, 4) + 270.0 * n2 - 330.0 * n2 * t * t) * Math.Pow(mo, 6);

            double ct13 = N * mo;
            double ct14 = (1.0 / 6.0) * (1.0 - t * t + n2) * N * Math.Pow(mo, 3);
            double ct15 = (1.0 / 120.0) * (5.0 - 18.0 * t * t + Math.Pow(t, 4) + 14.0 * n2 - 58.0 * n2 * t * t) * N * Math.Pow(mo, 5);//?????

            
            double ct16 = t * mo;
            double ct17 = (1.0 / 3.0) * (1.0 + 3 * n2 + 2 * n2 * n2) * t * Math.Pow(mo, 3);
            double ct18 = (1.0 / 15.0) * (2.0 - t * t) * t * Math.Pow(mo, 5);

            double xG = X + ct10 + ct11 + ct12;
            double yG = ct13 + ct14 + ct15;
            double xUTM = xG * kow;
            double ypUTM = yG * kow;
            double yUTM = 500000.0 + ypUTM;
            double HUTM = ct16 + ct17 + ct18;

            xyh.X = xUTM;
            xyh.Y = yUTM;
            xyh.Z = H;
          

            return xyh;
        }

        public static void xy2BL(double Lo, double a, double b, double e2, double kow, double xUTM, double yUTM)
        {
            
            yUTM = yUTM - 500000.0;
            double k = yUTM / kow;
            double Ko = 0.002526250890;
            double K2 = -0.000014923622;
            double K4 = 0.000000120770;
            double K6 = -0.000000001076;
            double Bos = xUTM / kow / 6367449.1458;
            double Bo;
            Bo = Bos + Math.Sin(2.0 * Bos) * (Ko + K2 * Math.Pow(Math.Sin(Bos), 2) + K4 * Math.Pow(Math.Sin(Bos), 4) + K6 * Math.Pow(Math.Sin(Bos), 6));
            double to = Math.Tan(Bo);
            double nyo = Math.Sqrt(ep2) * Math.Cos(Bo);
            double No = a / Math.Sqrt(1.0 - e2 * Math.Sin(Bo) * Math.Sin(Bo));
            double Mo = a * (1.0 - e2) / Math.Sqrt(Math.Pow(1.0 - e2 * Math.Pow(Math.Sin(Bo), 2), 3));
            B = Bo - (to * k * k / (2.0 * Mo * No) - to / (24.0 * Mo * Math.Pow(No, 3)) * (5.0 + 3.0 * to * to + Math.Pow(nyo, 2) - Math.Pow(3.0 * nyo * to, 2)) * Math.Pow(k, 4) - to / (720.0 * Mo * Math.Pow(No, 5)) * (61.0 + 90.0 * to * to + 45.0 * Math.Pow(to, 4)) * Math.Pow(k, 6));
            double l = (1.0 / (No * Math.Cos(Bo)) * k - 1.0 / (6.0 * Math.Pow(No, 3) * Math.Cos(Bo)) * (1.0 + 2.0 * Math.Pow(to, 2) + nyo * nyo) * Math.Pow(k, 3) + 1.0 / (120.0 * Math.Pow(No, 5) * Math.Cos(Bo)) * (5.0 + 28.0 * Math.Pow(to, 2) + 24.0 * Math.Pow(to, 4) + 6.0 * nyo * nyo + 8.0 * Math.Pow(nyo * to, 2)) * Math.Pow(k, 5));
            L = Lo + l;
            doi_ra_dpg(B);
            dB = dd;
            pB = ppp;
            gB = gg;
            doi_ra_dpg(L);
            dL = dd;
            pL = ppp;
            gL = gg;
        }


        public static Point3D xy2BL_v2(double Lo, double ko, double xUTM, double yUTM)
        {
            //double a, double b, double e2, double kow,
            Point3D pointout = new Point3D();
            double a = WGS_84.a;
            double e2 = WGS_84.e2;
            double b=WGS_84.b;
            //double  sta double kow6 = 0.9996;
            double kow = ko;

            yUTM = yUTM - 500000.0;
            double k = yUTM / kow;
            double Ko = 0.002526250890;
            double K2 = -0.000014923622;
            double K4 = 0.000000120770;
            double K6 = -0.000000001076;
            double Bos = xUTM / kow / 6367449.1458;
            double Bo;
            Bo = Bos + Math.Sin(2.0 * Bos) * (Ko + K2 * Math.Pow(Math.Sin(Bos), 2) + K4 * Math.Pow(Math.Sin(Bos), 4) + K6 * Math.Pow(Math.Sin(Bos), 6));
            double to = Math.Tan(Bo);
            double nyo = Math.Sqrt(ep2) * Math.Cos(Bo);
            double No = a / Math.Sqrt(1.0 - e2 * Math.Sin(Bo) * Math.Sin(Bo));
            double Mo = a * (1.0 - e2) / Math.Sqrt(Math.Pow(1.0 - e2 * Math.Pow(Math.Sin(Bo), 2), 3));
            B = Bo - (to * k * k / (2.0 * Mo * No) - to / (24.0 * Mo * Math.Pow(No, 3)) * (5.0 + 3.0 * to * to + Math.Pow(nyo, 2) - Math.Pow(3.0 * nyo * to, 2)) * Math.Pow(k, 4) - to / (720.0 * Mo * Math.Pow(No, 5)) * (61.0 + 90.0 * to * to + 45.0 * Math.Pow(to, 4)) * Math.Pow(k, 6));
            double l = (1.0 / (No * Math.Cos(Bo)) * k - 1.0 / (6.0 * Math.Pow(No, 3) * Math.Cos(Bo)) * (1.0 + 2.0 * Math.Pow(to, 2) + nyo * nyo) * Math.Pow(k, 3) + 1.0 / (120.0 * Math.Pow(No, 5) * Math.Cos(Bo)) * (5.0 + 28.0 * Math.Pow(to, 2) + 24.0 * Math.Pow(to, 4) + 6.0 * nyo * nyo + 8.0 * Math.Pow(nyo * to, 2)) * Math.Pow(k, 5));
            L = Lo + l;
            //doi_ra_dpg(B);
            //dB = dd;
            //pB = ppp;
            //gB = gg;
            //doi_ra_dpg(L);
            //dL = dd;
            //pL = ppp;
            //gL = gg;
            //pointout = new PointF((float)(B * 180 / Math.PI), (float)(L * 180 / Math.PI));
            pointout.X=B;// = new PointF((float)(B), (float)(L));
            pointout.Y = L;
            return pointout;
        }

        public static Point3D xyz2enu(Point3D xyz, Point3D orgxyz)
        {
            Point3D tmpxyz = xyz;
            Point3D tmporg = orgxyz;

            double[] Mtmpxyz =new double[3] { tmpxyz.X, tmpxyz.Y, tmpxyz.Z };
            //Matrix Mtmpxyz = new Matrix(new double[3] { tmpxyz.X,tmpxyz.Y, tmpxyz.Z  });
            //Matrix Mtmporg = new Matrix(new double[3] { orgxyz.X,orgxyz.Y, orgxyz.Z  });
            double[] Mtmporg = new double[3] { orgxyz.X, orgxyz.Y, orgxyz.Z };
            //Matrix difxyz = Mtmpxyz - Mtmporg;
            double[] difxyz = new double[3];
            for(int i=0;i<3;i++)
            { difxyz[i] = Mtmpxyz[i] - Mtmporg[i]; }
            //int m= difxyz
            //[m,n] = size(difxyz); if m<n, difxyz=difxyz'; end,
            //difxyz.Transpose();
            Point3D orgllh = xyz2llh(orgxyz);
            double phi = orgllh.X;
            double lam = orgllh.Y;
            double sinphi = Math.Sin(phi);
            double cosphi = Math.Cos(phi);
            double sinlam = Math.Sin(lam);
            double coslam = Math.Cos(lam);

          
            //Matrix R = new Matrix(new double[,] {{-sinlam, coslam, 0},{-sinphi*coslam,  -sinphi*sinlam,  cosphi}, {cosphi*coslam,cosphi*sinlam,sinphi}} );
            double[][] R = new double[3][];
            //double[][] R = new double[3][] { { -sinlam, coslam, 0 }, { -sinphi * coslam, -sinphi * sinlam, cosphi }, { cosphi * coslam, cosphi * sinlam, sinphi } };
            for (int i = 0; i < 3; i++)
            {
                R[0] = new double[3]{ -sinlam, coslam, 0 };
                R[1] = new double[3] { -sinphi * coslam, -sinphi * sinlam, cosphi };
                R[2] = new double[3] { cosphi * coslam, cosphi * sinlam, sinphi };
                
            }

            //Matrix enu = R*difxyz;
            double[] enu = pmatrix.MatrixVectorProduct(R, difxyz);
            Point3D pointout = new Point3D();
            pointout.X = enu[0];
            pointout.Y = enu[1];
            pointout.Z = enu[2];
            return pointout;

        }

    public static Point3D xyz2llh(Point3D xyz)
    {
	 double   x = xyz.X;
	 double  y = xyz.Y;
	 double  z = xyz.Z;
	 double  x2 = Math.Pow(x,2);
	 double  y2 = Math.Pow(y,2);
	 double  z2 = Math.Pow(z,2);
     double a = WGS84.a;// 6378137.0000;
     double b = WGS84.b;//6356752.31424518;	
	 double  e = Math.Sqrt (1.0-Math.Pow((b/a),2));
	 double  b2 = b*b;
	 double  e2 = Math.Pow(e,2);
	 double  ep = e*(a/b);
	 double  r = Math.Sqrt(x2+y2);
	 double  r2 = r*r;
	 double  E2 = Math.Pow(a,2) - Math.Pow(b,2);
	 double  F = 54.0*b2*z2;
	 double  G = r2 + (1.0-e2)*z2 - e2*E2;
	 double  c = (e2*e2*F*r2)/(G*G*G);
	 double  s = Math.Pow(( 1.0 + c + Math.Sqrt(c*c + 2*c) ),(1.0/3.0));
	 double  P = F / (3.0 * Math.Pow((s+1/s+1),2) * G*G);
	 double  Q = Math.Sqrt(1.0+2.0*e2*e2*P);
	 double  ro = -(P*e2*r)/(1.0+Q) + Math.Sqrt((a*a/2.0)*(1+1/Q) - (P*(1.0-e2)*z2)/(Q*(1.0+Q)) - P*r2/2.0);
	double  tmp = Math.Pow((r - e2*ro),2);
	double  U = Math.Sqrt( tmp + z2 );
	double  V = Math.Sqrt( tmp + (1.0-e2)*z2 );
	double  zo = (b2*z)/(a*V);
    
	double  height = U*( 1.0 - b2/(a*V) );
	
	double  lat = Math.Atan( (z + ep*ep*zo)/r );
    double Lng;
	double  temp = Math.Atan(y/x);
	    if (x >=0) 	
		    Lng = temp;
	    else if ((x < 0) && (y >= 0))
		    Lng = Math.PI + temp;
	    else
		    Lng = temp - Math.PI;
	   
    Point3D outpoint=new Point3D();
	    outpoint.X = lat;
	    outpoint.Y=Lng;
        outpoint.Z = height;
        return outpoint;
    }

        public static  Point3D llh2xyz(Point3D llh)
        {
	      double  phi = llh.X;
	       double lambda = llh.Y;
	       double  h = llh.Z;

	        double a = 6378137.0000;	// earth semimajor axis in meters
	        //double b = 6356752.3142;	// earth semiminor axis in meters	
            double f = 1.0 / 298.257223563;
                            
            //double b = a * (1.0 - f);
            //double b = 6356752.3142478;
            double b = 6356752.31424518;
	        double e = Math.Sqrt (1.0-Math.Pow((b/a),2));

	        double sinphi = Math.Sin(phi);
	        double cosphi = Math.Cos(phi);
	        double coslam = Math.Cos(lambda);
	        double sinlam = Math.Sin(lambda);
	        double tan2phi = Math.Pow((Math.Tan(phi)),2);
	        double tmp = 1.0 - e*e;
	        double tmpden = Math.Sqrt( 1.0 + tmp*tan2phi );

	        double x = (a*coslam)/tmpden + h*coslam*cosphi;

	        double y = (a*sinlam)/tmpden + h*sinlam*cosphi;

	        double tmp2 = Math.Sqrt(1.0 - e*e*sinphi*sinphi);
	        double z = (a*tmp*sinphi)/tmp2 + h*sinphi;
            Point3D pointout = new Point3D();
            pointout.X = x;
            pointout.Y = y;
            pointout.Z = z;
            return pointout;
        }

        public static Point3D llh2vn2000(double L0, double k0, Point3D llh)
        {
            double phi = llh.X;
            double lambda = llh.Y;
            double h = llh.Z;

            double a = 6378137.0000;	// earth semimajor axis in meters
            //double b = 6356752.314;	// earth semiminor axis in meters	
            //double b = 6356752.3142478;
            double b = 6356752.31424518;

            double e = Math.Sqrt(1.0 - Math.Pow((b / a), 2));

    
            double sinphi = Math.Sin(phi);
            double cosphi = Math.Cos(phi);
            double coslam = Math.Cos(lambda);
            double sinlam = Math.Sin(lambda);
            double tan2phi = Math.Pow((Math.Tan(phi)), 2);
            double tmp = 1.0 - e * e;
            double tmpden = Math.Sqrt(1.0 + tmp * tan2phi);

            double x = (a * coslam) / tmpden + h * coslam * cosphi;

            double y = (a * sinlam) / tmpden + h * sinlam * cosphi;

            double tmp2 = Math.Sqrt(1 - e * e * sinphi * sinphi);
            double z = (a * tmp * sinphi) / tmp2 + h * sinphi;
            Point3D ECEF = new Point3D();
            ECEF.X = x;
            ECEF.Y = y;
            ECEF.Z = z;


   
            //// Bo TNMT
            double ro = Math.PI / (180.0 * 3600.0);
            double dX0 = 191.90441429;
            double dY0 = 39.30318279;
            double dZ0 = 111.45032835;
            double omega0 = 0.00928836 * ro;
            double phi0 = -0.01975479 * ro;
            double epsilon0 = 0.00427372 * ro;
            double k = 0.999999747093722;
            //double k = 1.000000252906278;

            double Xv = dX0 + k * (x + epsilon0 * y - phi0 * z);
            double Yv = dY0 + k * (-epsilon0 * x + y + omega0 * z);
            double Zv = dZ0 + k * (phi0 * x - omega0 * y + z);

            Point3D XYZv=new Point3D();
            XYZv.X=Xv;
            XYZv.Y=Yv;
            XYZv.Z=Zv;
            Point3D LLHv = xyz2llh(XYZv);
            Point3D xyhv = BLH2xyh(L0, k0, LLHv.X, LLHv.Y, LLHv.Z);
            
            return xyhv;
        }
        /// <summary>
        /// 2021,1023 compensated
        /// </summary>
        /// <param name="datum"></param>
        /// <param name="llh"></param>
        /// <returns></returns>
        public static Point3D llh2NEH(C_Datum datum, Point3D llh)////2021,1023 compensated
        {
            Point3D xyhv = new Point3D();
            if (datum.datum_type > 2)
            {
                Point3D llhorg=new Point3D();
                llhorg.X=datum.False_Northing*Math.PI/180.0;
                llhorg.Y=datum.False_Easting*Math.PI/180.0;
                llhorg.Z=datum.False_H;
                Point3D neu = llh2enu(llh, llhorg);
                double[] tranpara = new double[5];
                tranpara[0] = datum.dX;
                tranpara[1] = datum.dY;
                tranpara[2] = datum.dZ;
                tranpara[3] = datum.rZ;
                tranpara[4] = datum.kT;
                
                Point3D PT4 = new Point3D();
                PT4 = Trans_para.TransFrom(neu, tranpara); //Tính thử tham số xuôi
                xyhv = PT4;
            }
            else
            {
                double phi = llh.X;
                double lambda = llh.Y;
                double h = llh.Z;


                double a = datum.elip.a;	// earth semimajor axis in meters
                //double b = 6356752.314;	// earth semiminor axis in meters	
                //double b = 6356752.3142478;
                double b = datum.elip.b;

                double e = Math.Sqrt(1.0 - Math.Pow((b / a), 2));


                double sinphi = Math.Sin(phi);
                double cosphi = Math.Cos(phi);
                double coslam = Math.Cos(lambda);
                double sinlam = Math.Sin(lambda);
                double tan2phi = Math.Pow((Math.Tan(phi)), 2);
                double tmp = 1.0 - e * e;
                double tmpden = Math.Sqrt(1.0 + tmp * tan2phi);

                double x = (a * coslam) / tmpden + h * coslam * cosphi;

                double y = (a * sinlam) / tmpden + h * sinlam * cosphi;

                double tmp2 = Math.Sqrt(1 - e * e * sinphi * sinphi);
                double z = (a * tmp * sinphi) / tmp2 + h * sinphi;
                Point3D ECEF = new Point3D();
                ECEF.X = x;
                ECEF.Y = y;
                ECEF.Z = z;

                double Xv = x;
                double Yv = y;
                double Zv = z;

                //// Bo TNMT
                double ro = Math.PI / (180.0 * 3600.0);
                double dX0 = datum.dX;
                double dY0 = datum.dY;
                double dZ0 = datum.dZ;
                double omega0 = datum.rX * ro;
                double phi0 = datum.rY * ro;
                double epsilon0 = datum.rZ * ro;
                double k = datum.kT;
                //double k = 1.000000252906278;
                //if (datum.Para_Model == 0)
                {
                    Xv = dX0 + k * (x + epsilon0 * y - phi0 * z);
                    Yv = dY0 + k * (-epsilon0 * x + y + omega0 * z);
                    Zv = dZ0 + k * (phi0 * x - omega0 * y + z);
                }
                ////else
                ////{
                ////    Xv = dX0 + (1.0 + k) * (x + epsilon0 * y - phi0 * z);
                ////    Yv = dY0 + (1.0 + k) * (-epsilon0 * x + y + omega0 * z);
                ////    Zv = dZ0 + (1.0 + k) * (phi0 * x - omega0 * y + z);
                ////}


                Point3D XYZv = new Point3D();
                XYZv.X = Xv;
                XYZv.Y = Yv;
                XYZv.Z = Zv;
                Point3D LLHv = xyz2llh(XYZv);
                if (datum.Res_update == true) //////////Change here 10/8/2021///////////
                {
                    LLHv.X = LLHv.X + datum.resB;
                    LLHv.Y = LLHv.Y + datum.resL;
                    LLHv.Z = LLHv.Z + datum.resH;
                }

                xyhv = BLH2xyh(datum.L0, datum.k0, LLHv.X, LLHv.Y, LLHv.Z);
                if (datum.shift_cors == true) //////////Change here 10/8/2021///////////
                {
                    xyhv.X = xyhv.X + datum.resN;
                    xyhv.Y = xyhv.Y + datum.resE;
                    xyhv.Z = xyhv.Z + datum.resHS;
                }
                

            }
            return xyhv;
        }

        public static Point3D llh2NEH_HM(C_Datum datum, Point3D llh)
        {
            Point3D xyhv = new Point3D();
           
            
                double phi = llh.X;
                double lambda = llh.Y;
                double h = llh.Z;


                double a = datum.elip.a;	// earth semimajor axis in meters

                double b = datum.elip.b;

                double e = Math.Sqrt(1.0 - Math.Pow((b / a), 2));


                double sinphi = Math.Sin(phi);
                double cosphi = Math.Cos(phi);
                double coslam = Math.Cos(lambda);
                double sinlam = Math.Sin(lambda);
                double tan2phi = Math.Pow((Math.Tan(phi)), 2);
                double tmp = 1.0 - e * e;
                double tmpden = Math.Sqrt(1.0 + tmp * tan2phi);

                double x = (a * coslam) / tmpden + h * coslam * cosphi;

                double y = (a * sinlam) / tmpden + h * sinlam * cosphi;

                double tmp2 = Math.Sqrt(1 - e * e * sinphi * sinphi);
                double z = (a * tmp * sinphi) / tmp2 + h * sinphi;
                Point3D ECEF = new Point3D();
                ECEF.X = x;
                ECEF.Y = y;
                ECEF.Z = z;

                double Xv = x;
                double Yv = y;
                double Zv = z;

                //// Bo TNMT
                //double ro = Math.PI / (180.0 * 3600.0);
                
                double[] tranpara=new double[7];
                tranpara[0]=datum.dX;
                tranpara[1]=datum.dY;
                tranpara[2]= datum.dZ;
                tranpara[3]=datum.rX;
                tranpara[4]=datum.rY;
                tranpara[5]=datum.rZ;
                tranpara[6] = datum.kT;

                Point3D XYZv = Trans_para.HMTransFrom3D(ECEF, tranpara);
              
                Point3D LLHv = xyz2llh(XYZv);
                xyhv = BLH2xyh(datum.L0, datum.k0, LLHv.X, LLHv.Y, LLHv.Z);
            
            
            return xyhv;
        }

        public static Point3D vn20002llh(double L0, double ko, Point3D xyh)
        {
            

            Point3D BL = xy2BL_v2(L0, ko, xyh.X, xyh.Y);
            double H = xyh.Z;
            Point3D llh=new Point3D();
            llh.X=BL.X;
            llh.Y=BL.Y;
            llh.Z=H;
            Point3D XYZ = llh2xyz(llh);


            double ro = Math.PI / (180.0 * 3600.0);
            double dX0 = -191.90441429;
            double dY0 = -39.30318279;
            double dZ0 = -111.45032835;
            double omega0 = -0.00928836 * ro;
            double phi0 = 0.01975479 * ro;
            double epsilon0 = -0.00427372 * ro;
            double k = 1.000000252906278;

                     

            double Xv = dX0 + k * (XYZ.X + epsilon0 * XYZ.Y - phi0 * XYZ.Z);
            double Yv = dY0 + k * (-epsilon0 * XYZ.X + XYZ.Y + omega0 * XYZ.Z);
            double Zv = dZ0 + k * (phi0 * XYZ.X - omega0 * XYZ.Y + XYZ.Z);

            Point3D XYZv = new Point3D();
            XYZv.X = Xv;
            XYZv.Y = Yv;
            XYZv.Z = Zv;
            Point3D LLHv = xyz2llh(XYZv);
            //Point3D xyhv = BLH2xyh(L0, LLHv.X, LLHv.Y, LLHv.Z);
            return LLHv;
        }

        /// <summary>
        /// 2021,1023 compensated
        /// </summary>
        /// <param name="datum"></param>
        /// <param name="xyh"></param>
        /// <returns></returns>
        public static Point3D NEH2llh(C_Datum datum, Point3D xyh)////2021,1023 compensated
        {
            

            if (datum.shift_cors == true)//////////Change here 21/5/2020///////////
            {
                xyh.X = xyh.X - datum.resN;
                xyh.Y = xyh.Y - datum.resE;
                xyh.Z = xyh.Z - datum.resHS;
            }
 
            Point3D LLHv = new Point3D();
            if (datum.datum_type > 2)
            {
                double[] tranparaR = new double[5];
                tranparaR[0] = datum.rX;
                tranparaR[1] = datum.rY;
                tranparaR[2] = -datum.dZ;
                tranparaR[3] = -datum.rZ;
                tranparaR[4] = 1.0 / datum.kT;

                Point3D neu = new Point3D();
                neu = Trans_para.TransFrom(xyh, tranparaR); //Tính thử tham số nguoc
                Point3D llhorg = new Point3D();
                llhorg.X = datum.False_Northing * Math.PI / 180.0;
                llhorg.Y = datum.False_Easting * Math.PI / 180.0;
                llhorg.Z = datum.False_H;
                LLHv = BL2xy.enu2llh(neu, llhorg);
     
            }
            else
            {

                Point3D BL = xy2BL_v2(datum.L0, datum.k0, xyh.X, xyh.Y);
                double H = xyh.Z;
                //NEH2BLH(Lo, ko, NEH[0], NEH[1], NEH[2], llh);
                
                Point3D llh = new Point3D();

                llh.X = BL.X;
                llh.Y = BL.Y;
                llh.Z = H;

                if (datum.Res_update == true) //////////Change here 10/8/2021///////////
                {
                    llh.X = llh.X - datum.resB;
                    llh.Y = llh.Y - datum.resL;
                    llh.Z = llh.Z - datum.resH;
                }

                Point3D XYZ = llh2xyz(llh);


                double ro = Math.PI / (180.0 * 3600.0);
                double dX0 = -datum.dX;
                double dY0 = -datum.dY;
                double dZ0 = -datum.dZ;
                double omega0 = -datum.rX * ro;
                double phi0 = -datum.rY * ro;
                double epsilon0 = -datum.rZ * ro;
                double k = 1.0 / datum.kT;

                double Xv = XYZ.X;
                double Yv = XYZ.Y;
                double Zv = XYZ.Z;

                //if (datum.Para_Model == 0)
                {
                    Xv = dX0 + k * (XYZ.X + epsilon0 * XYZ.Y - phi0 * XYZ.Z);
                    Yv = dY0 + k * (-epsilon0 * XYZ.X + XYZ.Y + omega0 * XYZ.Z);
                    Zv = dZ0 + k * (phi0 * XYZ.X - omega0 * XYZ.Y + XYZ.Z);
                }
                //else
                //{
                //    Xv = dX0 + (1.0 + k) * (XYZ.X + epsilon0 * XYZ.Y - phi0 * XYZ.Z);
                //    Yv = dY0 + (1.0 + k) * (-epsilon0 * XYZ.X + XYZ.Y + omega0 * XYZ.Z);
                //    Zv = dZ0 + (1.0 + k) * (phi0 * XYZ.X - omega0 * XYZ.Y + XYZ.Z);
                //}

                Point3D XYZv = new Point3D();
                XYZv.X = Xv;
                XYZv.Y = Yv;
                XYZv.Z = Zv;
                LLHv = xyz2llh(XYZv);
            }
            return LLHv;
        }

        public static Point3D XYZ2vn2000(double L0, double k0, Point3D XYZ)//
        {
            
            double a = 6378137.0000;	// earth semimajor axis in meters
            //double b = 6356752.314;	// earth semiminor axis in meters	
            //double b = 6356752.3142478;
            double b = 6356752.31424518;

            double e = Math.Sqrt(1.0 - Math.Pow((b / a), 2));

            double x = XYZ.X;
            double y = XYZ.Y;
            double z = XYZ.Z;
                       
            //// Bo TNMT
            double ro = Math.PI / (180.0 * 3600.0);
            double dX0 = 191.90441429;
            double dY0 = 39.30318279;
            double dZ0 = 111.45032835;
            double omega0 = 0.00928836 * ro;
            double phi0 = -0.01975479 * ro;
            double epsilon0 = 0.00427372 * ro;
            double k = 0.999999747093722;
            //double k = 1.000000252906278;

            double Xv = dX0 + k * (x + epsilon0 * y - phi0 * z);
            double Yv = dY0 + k * (-epsilon0 * x + y + omega0 * z);
            double Zv = dZ0 + k * (phi0 * x - omega0 * y + z);

            Point3D XYZv = new Point3D();
            XYZv.X = Xv;
            XYZv.Y = Yv;
            XYZv.Z = Zv;
            Point3D LLHv = xyz2llh(XYZv);
            Point3D xyhv = BLH2xyh(L0, k0, LLHv.X, LLHv.Y, LLHv.Z);
            return xyhv;
        }

        public static Point3D NEH2XYZ(C_Datum datum, Point3D xyh)
        {
            Point3D BL = xy2BL_v2(datum.L0, datum.k0, xyh.X, xyh.Y);
            double H = xyh.Z;
            Point3D llh = new Point3D();
            llh.X = BL.X;
            llh.Y = BL.Y;
            llh.Z = H;
            Point3D XYZ = llh2xyz(llh);


            double ro = Math.PI / (180.0 * 3600.0);
            double dX0 = -datum.dX;
            double dY0 = -datum.dY;
            double dZ0 = -datum.dZ;
            double omega0 = -datum.rX * ro;
            double phi0 = -datum.rY * ro;
            double epsilon0 = -datum.rZ * ro;
            double k = 1.0 / datum.kT;
            double Xv = XYZ.X;
            double Yv = XYZ.Y;
            double Zv = XYZ.Z;

            //if (datum.Para_Model == 0)
            {
                Xv = dX0 + k * (XYZ.X + epsilon0 * XYZ.Y - phi0 * XYZ.Z);
                Yv = dY0 + k * (-epsilon0 * XYZ.X + XYZ.Y + omega0 * XYZ.Z);
                Zv = dZ0 + k * (phi0 * XYZ.X - omega0 * XYZ.Y + XYZ.Z);
            }
            //else
            //{
            //    Xv = dX0 + (1.0 + k) * (XYZ.X + epsilon0 * XYZ.Y - phi0 * XYZ.Z);
            //    Yv = dY0 + (1.0 + k) * (-epsilon0 * XYZ.X + XYZ.Y + omega0 * XYZ.Z);
            //    Zv = dZ0 + (1.0 + k) * (phi0 * XYZ.X - omega0 * XYZ.Y + XYZ.Z);
            //}

            Point3D XYZv = new Point3D();
            XYZv.X = Xv;
            XYZv.Y = Yv;
            XYZv.Z = Zv;
            return XYZv;
        }

        public static Point3D XYZ2NEH(C_Datum datum, Point3D XYZ)
        {

            double a = datum.elip.a;	// earth semimajor axis in meters
            double b = datum.elip.b;
            //double a = 6378137.0000;	// earth semimajor axis in meters
            //double b = 6356752.31424518;
            double e = Math.Sqrt(1.0 - Math.Pow((b / a), 2));

            double x = XYZ.X;
            double y = XYZ.Y;
            double z = XYZ.Z;

            //// Bo TNMT
            double ro = Math.PI / (180.0 * 3600.0);
            double dX0 = datum.dX;
            double dY0 = datum.dY;
            double dZ0 = datum.dZ;
            double omega0 = datum.rX * ro;
            double phi0 = datum.rY * ro;
            double epsilon0 = datum.rZ * ro;
            double k = datum.kT;
            //double k = 1.000000252906278;

            double Xv=x;
            double Yv=y;
            double Zv = z;

            //if (datum.Para_Model == 0)
            {
                Xv = dX0 + k * (x + epsilon0 * y - phi0 * z);
                Yv = dY0 + k * (-epsilon0 * x + y + omega0 * z);
                Zv = dZ0 + k * (phi0 * x - omega0 * y + z);
            }
            ////else
            ////{
            ////    Xv = dX0 + (1.0 + k) * (x + epsilon0 * y - phi0 * z);
            ////    Yv = dY0 + (1.0 + k) * (-epsilon0 * x + y + omega0 * z);
            ////    Zv = dZ0 + (1.0 + k) * (phi0 * x - omega0 * y + z);
            ////}

            Point3D XYZv = new Point3D();
            XYZv.X = Xv;
            XYZv.Y = Yv;
            XYZv.Z = Zv;
            Point3D LLHv = xyz2llh(XYZv);
            Point3D xyhv = BLH2xyh(datum.L0, datum.k0, LLHv.X, LLHv.Y, LLHv.Z);
            return xyhv;
        }



        public static Point3D enu2xyz(Point3D enu,Point3D orgxyz)
        {


            //[m,n]=size(enu);if m<n,tmpenu=enu'; else,tmpenu=enu;end
            //[m,n]=size(orgxyz);if m<n,tmpxyz=orgxyz';else,tmpxyz=orgxyz;end
            //Matrix tmpenu=new Matrix(new double[3] {enu.X, enu.Y, enu.Z});
            double[] tmpenu = new double[3] { enu.X, enu.Y, enu.Z };
            //pmatrix tmpenu1=new pmatrix();
            //tmpenu.Transpose();
            //Matrix Mtmpxyz=new Matrix(new double[3] {orgxyz.X, orgxyz.Y, orgxyz.Z});
            Point3D Mtmpxyz = new Point3D(orgxyz.X, orgxyz.Y, orgxyz.Z);
            //Mtmpxyz.Transpose();
            Point3D tmpxyz=orgxyz;
            Point3D orgllh = xyz2llh(tmpxyz);
            double phi = orgllh.X;
            double lam = orgllh.Y;
            double sinphi = Math.Sin(phi);
            double cosphi = Math.Cos(phi);
            double sinlam = Math.Sin(lam);
            double coslam = Math.Cos(lam);


            


            //Matrix R = new Matrix(new double[,] {{-sinlam, coslam, 0},{-sinphi*coslam,  -sinphi*sinlam,  cosphi}, {cosphi*coslam,cosphi*sinlam,sinphi}} );
            double[][] R = new double[3][];
            //double[][] R = new double[3][] { { -sinlam, coslam, 0 }, { -sinphi * coslam, -sinphi * sinlam, cosphi }, { cosphi * coslam, cosphi * sinlam, sinphi } };
            for (int i = 0; i < 3; i++)
            {
                R[0] = new double[3] { -sinlam, coslam, 0 };
                R[1] = new double[3] { -sinphi * coslam, -sinphi * sinlam, cosphi };
                R[2] = new double[3] { cosphi * coslam, cosphi * sinlam, sinphi };

            }

            //Matrix enu = R*difxyz;
            //double[] enu = pmatrix.MatrixVectorProduct(R, difxyz);


            //Matrix R=new Matrix(new double[,]{{-sinlam,coslam,0},{-sinphi*coslam,  -sinphi*sinlam,  cosphi},{cosphi*coslam,   cosphi*sinlam,  sinphi}});
            R = pmatrix.MatrixInverse(R);
            //Matrix difxyz =R.Inverse() *tmpenu;
            double[] difxyz = pmatrix.MatrixVectorProduct(R, tmpenu);

            //Matrix xyz = Mtmpxyz + difxyz;
            double[] xyz=new double[3] { Mtmpxyz.X + difxyz[0], Mtmpxyz.Y + difxyz[1], Mtmpxyz.Z + difxyz[2] };
            Point3D pointout = new Point3D();
            //double a = Convert.ToDouble(xyz[1].ToString());
            pointout.X = Convert.ToDouble(xyz[1].ToString(), CultureInfo.GetCultureInfo("en-US"));
            pointout.Y = Convert.ToDouble(xyz[2].ToString(), CultureInfo.GetCultureInfo("en-US"));
            pointout.Z = Convert.ToDouble(xyz[3].ToString(), CultureInfo.GetCultureInfo("en-US"));
            return pointout;

        }

        public static Point3D llh2enu(Point3D llh, Point3D llhorg)
        {
            Point3D xyz_org = llh2xyz(llhorg);
            Point3D pos_xyzg = llh2xyz(llh);
            Point3D pos_enug = xyz2enu(pos_xyzg, xyz_org);
            return pos_enug;

        }

        public static Point3D enu2llh(Point3D enu, Point3D llhorg)
        {
            Point3D xyzorg = llh2xyz(llhorg);
            Point3D xyz = enu2xyz(enu, xyzorg);
            Point3D llh = xyz2llh(xyz);
            
            return llh;

        }
        public static Point3D benu2llh(Point3D enu, Point3D llhorg)
        {
            Point3D benu=new Point3D();
            benu.X = -enu.X;
            benu.Y = -enu.Y;
            benu.Z = -enu.Z;
            Point3D xyzorg = llh2xyz(llhorg);
            Point3D xyz = enu2xyz(benu, xyzorg);
            Point3D llh = xyz2llh(xyz);

            return llh;

        }
        /// <summary>
        /// Chuyen doi tu ENU sang DN, DE, DH (VN2000) tu Base den Rover
        /// </summary>
        /// <param name="datum"></param> Tham so he toa do
        /// <param name="enu"></param> enu output tu may thu
        /// <param name="rllh"></param> toa do llh tu rover
        /// <returns></returns>
        public static Point3D enu2dNEH(C_Datum datum, Point3D enu, Point3D rllh)
        {
            Point3D dNEH = new Point3D();
            Point3D rNEH= llh2NEH(datum, rllh);
            Point3D bllh = benu2llh(enu, rllh);
            Point3D bNEH = llh2NEH(datum, bllh);
            dNEH.X=rNEH.X-bNEH.X;
            dNEH.Y = rNEH.Y - bNEH.Y;
            dNEH.Z = rNEH.Z - bNEH.Z;
            return dNEH;
        }
        public static Point3D dned_to_llh(Point3D pos1,Point3D dned)
        {

                // deg to radian   deg*PI/180
             int i=0;
             double a,b,f,we,e2;
             double mid_lat, mid_h;
             double Rm,Rn;
             double[] dllh=new double[3];
             mid_lat = pos1.X ;
             mid_h = 0;
             a = 6378137.0;
             b = 6356752.31424518;;
             f = 1.0/298.2572236;
             we = 7.292115147e-5;
             e2 = 1 - Math.Pow((b/a),2);


             Rm = a*(1-e2)/Math.Pow((1-e2 * Math.Pow(Math.Sin(mid_lat ),2)),1.5);
             Rn = a/Math.Sqrt(1-e2 * Math.Pow(Math.Sin(mid_lat ),2));


             dllh[0] = dned.X/(Rm + mid_h);
             dllh[1] = dned.Y/((Rn + mid_h) * Math.Cos(mid_lat));
             dllh[2] = -dned.Z ;

             //for(i=0;i<3;i++)
             //    pos2[i] = pos1[i] + dllh[i];
             Point3D pos2 = new Point3D();
             pos2.X = pos1.X + dllh[0];
             pos2.Y = pos1.Y + dllh[1];
             pos2.Z = pos1.Z + dllh[2];
             return pos2;

        }

         public static Point2D dne_to_ll(Point2D pos1, Point2D dned)
         {

             // deg to radian   deg*PI/180
             int i = 0;
             double a, b, f, we, e2;
             double mid_lat, mid_h;
             double Rm, Rn;
             double[] dllh = new double[2];
             mid_lat = pos1.X;
             mid_h = 0;
             a = 6378137.0;
             b = 6356752.31424518;
             f = 1.0 / 298.2572236;
             we = 7.292115147e-5;
             e2 = 1 - Math.Pow((b / a), 2);


             Rm = a * (1 - e2) / Math.Pow((1 - e2 * Math.Pow(Math.Sin(mid_lat), 2)), 1.5);
             Rn = a / Math.Sqrt(1 - e2 * Math.Pow(Math.Sin(mid_lat), 2));


             dllh[0] = dned.X / (Rm + mid_h);
             dllh[1] = dned.Y / ((Rn + mid_h) * Math.Cos(mid_lat));
             //dllh[2] = -dned.Z;

             Point2D pos2 = new Point2D();
             pos2.X = pos1.X + dllh[0];
             pos2.Y = pos1.Y + dllh[1];
             return pos2;

         }
       
     


    }
   

}
