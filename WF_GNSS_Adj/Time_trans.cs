using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;

namespace WF_GNSS_Adj
{
    public class Time_trans
    {
        public double year{ get; set; }
        public double month{ get; set; }
        public double day{ get; set; }
        public double hh{ get; set; }
        public double mm{ get; set; }
        public double ss{ get; set; }
        public double gpsweek{ get; set; }
        public double gpss{ get; set; }
        public double gpsweeksecond { get; set; }
        public string timestring = "";//{ get; set; }

        public double ymd2mjd(double year, double month, double day)
        {
            // Add default century 
            if (year>=0 && year<=49)
            {
                year=year+2000;
            }
            else
            {
                if (year >= 50 && year <= 99)
                { year = year + 1900; }
            }
            // Validate year and month
           // Modified Julian Date 
            
            double mjd = Math.Floor((1461 * (year - Math.Floor((12 - month) / 10) + 4712)) / 4) +
                   Math.Floor((306 * ((month + 9) % 12) + 5) / 10) -
                   Math.Floor((3 * Math.Floor((year - Math.Floor((12.0 - month) / 10.0) + 4900) / 100)) / 4) +
                   day - 2399904;
            //mjd = 55865;
            return mjd;
            
        }
        public Time_trans mjd2gps(double mjd)
        {
            
            //function gps=mjd2gps(mjd)
            //////////%MJD2GPS Modified Julian Date to GPS Week and Second past Sunday 0hrs. 
            //////////%        MJD2YMD(mjd) returns the two-element row vector with the decimal
            //////////%        GPS week number and the number of seconds past midnight of last 
            //////////%        saturday/sunday
            //////////%
            //////////%           gps = [ GPSweek GPSsecond]
            //////////%
            //////////%        Input is the Modified Julian Date MJD (JD-2400000.5). If the 
            //////////%        Modified Julian Date is not OK the function returns a row vector 
            //////////%        of NaN's.

            //////////%        H. van der Marel, LGR, 29-04-95
            //////////%        (c) Geodetic Computing Centre, TU Delft

            //////////% Number of days since starting epoch of GPS weeks (Sunday 06-Jan-1980)
            double mjds = mjd - 44244;

            // Week number, day and second in week
             gpsweek = Math.Floor(mjds / 7);
             double daytemp = mjds - gpsweek * 7;
            gpss = daytemp * 86400;
            
            return new Time_trans(); 
        }
        public Time_trans utc2gpst(double year, double month, double day, double hh, double mm, double ss)
        {
            double mjd = this.ymd2mjd(year, month, day); 
            this.mjd2gps(mjd);
            gpss = gpss + 3600.0 * hh + 60.0 * mm + ss + 18.0;
            gpsweeksecond = gpsweek + gpss / 604800.0;
            //gpsweek = gpst(1);
            //secs = gpst(2);
            return new Time_trans();
        }
        public double Datetime2gpst(DateTime _datetime)
        {
            //double mjd = this.ymd2mjd( year, month, day);
            //double mjd = this.ymd2mjd((double)_datetime.Year, (double)_datetime.Month, (double)_datetime.Day);
            //this.mjd2gps(mjd);
            //gpss = gpss + 3600 * hh + 60 * mm + ss;
            //gpsweeksecond = gpsweek + gpss / 604800.0;
            Time_trans _timetran = new Time_trans();
            _timetran.utc2gpst(_datetime.Year, _datetime.Month, _datetime.Day, _datetime.Hour, _datetime.Minute, _datetime.Second+_datetime.Millisecond/1000.0);
            //gpsweek = gpst(1);
            //secs = gpst(2);
            return _timetran.gpss;
        }
        public Time_trans Datetime2timetrans(DateTime time)
        {
            Time_trans _timetran = new Time_trans();
           year = time.Year;
           month = time.Month;
           day = time.Day;
           hh = time.Hour;
           mm = time.Minute;
           ss = time.Second + time.Millisecond / 1000.0;
            double mjd = this.ymd2mjd(year,month, day);
            this.mjd2gps(mjd);
            gpss = gpss + 3600.0 * hh + 60.0 * mm + ss + 18.0;
            gpsweeksecond = gpsweek + gpss / 604800.0;
            
            return new Time_trans();
        }

    }//end of class
}
