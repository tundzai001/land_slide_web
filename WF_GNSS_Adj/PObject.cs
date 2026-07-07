/////This file include:
///// Class PFrame
///// Class HObject
///// Class PObject
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
//using GMap.NET;
//using GMap.NET.WindowsForms;
//using GMap.NET.WindowsForms.Markers;
using System.Drawing;
using System.Windows.Forms;
namespace WF_GNSS_Adj
{
    public class Point3D
    {
        public double X = 0;
        public double Y = 0;
        public double Z = 0;

        public Point3D(double p1, double p2, double p3)
        {
            X = p1;
            Y = p2;
            Z = p3;
        }
        public Point3D()
        {
            X = 0.0;
            Y = 0.0;
            Z = 0.0;
        }
        public static Point3D plus(Point3D p1, Point3D p2)
        {
            Point3D p12 = new Point3D();
            p12.X = p1.X + p2.X;
            p12.Y = p1.Y + p2.Y;
            p12.Z = p1.Z + p2.Z;
            return p12;
        }

        public static Point3D minus(Point3D p1, Point3D p2)
        {
            Point3D p12 = new Point3D();
            p12.X = p1.X - p2.X;
            p12.Y = p1.Y - p2.Y;
            p12.Z = p1.Z - p2.Z;
            return p12;
        }

        public static Point3D plus_std(Point3D p1, Point3D p2)
        {
            Point3D p12 = new Point3D();
            p12.X = Math.Sqrt(p1.X * p1.X + p2.X * p2.X);
            p12.Y = Math.Sqrt(p1.Y*p1.Y + p2.Y*p2.Y);
            p12.Z = Math.Sqrt(p1.Z * p1.Z + p2.Z * p2.Z);
            return p12;
        }

    }
    public class Point2D
    {
        public double X = 0;
        public double Y = 0;

        public Point2D()
        {
            X = 0.0;
            Y = 0.0;
        }
        public Point2D (double p1, double p2)
        {
            X=p1;
            Y=p2;
        }

    }
  
    public class HObject
    {
        
        //public PointLatLng llhorg=new PointLatLng();//set
        //public PointLatLng llhstart = new PointLatLng();//set
        //public PointLatLng llhpre = new PointLatLng();//set
        public double direction = 0;// get
        public double travelled = 0;// get
        public List<Point2D> profile = new List<Point2D>();//set
        public List<Point3D> profile3D = new List<Point3D>();//set
        public List<Point3D> att = new List<Point3D>();//set
        public Point2D curpointwold = new Point2D();
        public double MaxHeight = -9999;// get
        public double MinHeight = 99999;// get
        
        public double MinLength = 1000000000;//get
        public double MaxLength = -999;//get

        public double HeightScale = 1;//get
        public double LengthScale = 1;//get
        //public PointLatLng Basepoint = new PointLatLng(90,180);//get
        //public PointLatLng Maxpoint = new PointLatLng(0,0);//get
        //public GMapRoute HeightRoute;
        //public List<PointLatLng> profileworld = new List<PointLatLng>();//get
        public double HeightDist=0;//get
        public double LengthDist=0;//get
        public double profile_length = 0;
        public double profile_tickdis = 0;
        //public GMapOverlay overlay=new GMapOverlay();
        //public List<GMapMarkerImage> waypoints = new List<GMapMarkerImage>();
        //public int waypoint_num = 0;
        public void getRange()
        {
            //MaxHeight = profile.Max().X;
            //MaxLength = profile.Max().Y;
            //MinHeight = profile.Min().X;
            //MinLength = profile.Min().Y;
            foreach (Point2D ptf in profile)
            {


                if (ptf.X > MaxHeight) MaxHeight = ptf.X;
                if (ptf.X < MinHeight) MinHeight = ptf.X;
                
                if (ptf.Y > MaxLength) MaxLength = ptf.Y;
                if (ptf.Y < MinLength) MinLength = ptf.Y;
            }
         
        }
       

        public ContextMenuStrip ContextMenuStrip
        {
            get
            {
                return ContextMenuStrip;
            }
            set
            {
                ContextMenuStrip = value;
            }
        }
        
    }
     
    
    
    
}
