using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;

namespace WF_GNSS_Adj
{
    public class WGS_84
    {
     public static double a = 6378137.0;
	 public static double b = 6356752.31424518;
	 public static double f = 1.0/298.2572236;
     public static double we = 7.292115147e-5;
	 public static double e2 = 1 - Math.Pow((b/a),2);
	 public static double gm = 3986004.418e+8;
	 public static double j2 = 1.082626683e-3;
	 public static double j3 = -2.5327e-6;
    }
}
