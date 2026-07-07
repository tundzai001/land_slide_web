using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace WF_GNSS_Adj
{
    public class Adj
    {

        public static void GNSS_data_processing_FromFile(String Filename, int mode, C_Datum datum, rtmp_opt rtmpopt)
        {

          
            rtmpopt.list_fixpoint = new List<mopoint>();
            rtmpopt.list_adjpoint = new List<mopoint>();
            rtmpopt.list_moloop = new List<moloop>();
            rtmpopt.list_proloop = new List<moloop>();
            rtmpopt.list_mobaseline = new List<mobaseline>();
            rtmpopt.list_passedmobaseline = new List<mobaseline>();
            rtmpopt.list_probaseline = new List<mobaseline>();
            rtmpopt.list_adjbaseline = new List<mobaseline>();
            rtmpopt.report_flag = true;
            base_t[] m_base = new base_t[0];
            rtmpopt.backward = false;

            System.IO.StreamReader infile = new System.IO.StreamReader(Filename);
            if (infile == null)
            {
                MessageBox.Show(" No output file, Please input one");
                return;
            }
            else
            {


                rtmpopt.list_mopoint = new List<mopoint>();
                string line;
                bool getPoint = false;
                bool getBaseline = false;
                while ((line = infile.ReadLine()) != null)
                {
                    if (line.Contains("Point_name"))
                    {
                        getPoint = true;
                        getBaseline = false;
                        continue;
                    }
                    if (line.Contains("From_Point"))
                    {
                        getPoint = false;
                        getBaseline = true;
                        continue;
                    }

                    if (getPoint == true)
                    {
                        char[] delimiters1 = new char[] { ' ', ',', '\t' };
                        string[] parts1 = line.Split(delimiters1, StringSplitOptions.RemoveEmptyEntries);
                        int nfield = parts1.Length;

                        if (parts1.Length < 5)
                        {
                            MessageBox.Show("The input data is not valid");
                            continue;
                        }
                        else
                        {
                            mopoint mop = new mopoint();
                            mop.converted = true;
                            mop.processed = false;
                            mop.fromorto = -1;
                            mop.coef = 0;
                            mop.id = Convert.ToInt32(parts1[0]);
                            mop.basename = parts1[1];
                            mop.Appneu.X = Convert.ToDouble(parts1[2]);
                            mop.Appneu.Y = Convert.ToDouble(parts1[3]);
                            mop.Appneu.Z = Convert.ToDouble(parts1[4]);
                            if (parts1.Length >= 8)
                            {
                                mop.iniNEU_std.X = Convert.ToDouble(parts1[5]);
                                mop.iniNEU_std.Y = Convert.ToDouble(parts1[6]);
                                mop.iniNEU_std.Z = Convert.ToDouble(parts1[7]);
                                if (parts1.Length >= 9 && parts1[8].Contains("fix"))
                                {
                                    mop.fix = true;
                                    rtmpopt.nfix++;
                                }
                            }
                            else if (parts1[5].Contains("fix"))
                            {
                                mop.fix = true;
                                rtmpopt.nfix++;
                            }
                            rtmpopt.list_mopoint.Add(mop);

                        }
                    }
                    if (getBaseline == true)
                    {
                        char[] delimiters1 = new char[] { ' ', ',', '\t' };
                        string[] parts1 = line.Split(delimiters1, StringSplitOptions.RemoveEmptyEntries);
                        int nfield = parts1.Length;

                        if (parts1.Length < 9)
                        {
                            MessageBox.Show("The input data is not valid");
                            continue;
                        }
                        else
                        {
                            mobaseline baseline = new mobaseline();
                            foreach (var mp in rtmpopt.list_mopoint)
                            {
                                if (mp.basename == parts1[1])
                                {
                                    baseline.frompoint = baseline.vector[0] = mp;
                                    break;
                                }
                            }
                            foreach (var mp in rtmpopt.list_mopoint)
                            {
                                if (mp.basename == parts1[2])
                                {
                                    baseline.topoint = baseline.vector[1] = mp;
                                    break;
                                }
                            }
                            if (baseline.frompoint != null && baseline.topoint != null)
                            {

                                baseline.dneu.X = Convert.ToDouble(parts1[3], CultureInfo.GetCultureInfo("en-US"));
                                baseline.dneu.Y = Convert.ToDouble(parts1[4], CultureInfo.GetCultureInfo("en-US"));
                                baseline.dneu.Z = Convert.ToDouble(parts1[5], CultureInfo.GetCultureInfo("en-US"));
                                baseline.std.X = Convert.ToDouble(parts1[6], CultureInfo.GetCultureInfo("en-US"));
                                baseline.std.Y = Convert.ToDouble(parts1[7], CultureInfo.GetCultureInfo("en-US"));
                                baseline.std.Z = Convert.ToDouble(parts1[8], CultureInfo.GetCultureInfo("en-US"));
                                baseline.hstd = Convert.ToDouble(parts1[6], CultureInfo.GetCultureInfo("en-US"));
                                baseline.vstd = Convert.ToDouble(parts1[8], CultureInfo.GetCultureInfo("en-US"));
                                baseline.length = Math.Sqrt(baseline.dneu.X * baseline.dneu.X + baseline.dneu.Y * baseline.dneu.Y + baseline.dneu.Z * baseline.dneu.Z);
                                baseline.processed = 1;
                                rtmpopt.list_mobaseline.Add(baseline);
                                rtmpopt.list_probaseline.Add(baseline);
                            }
                        }
                    }
                }


            }
            infile.Close();






            if (rtmpopt.list_mopoint.Count < 1)
            {
                return;
            }


            if (rtmpopt.nfix == 0)//Nếu không có điểm gốc nào thì lấy điểm quan trắc đầu tiên làm gốc
            {
                rtmpopt.list_mopoint[0].fix = true;
            }




            //in cac canh baseline
            if (rtmpopt.list_probaseline.Count > 0)
            {
                rtmpopt.tmp_String = new System.IO.StringWriter();
                rtmpopt.print_Baseline_to_String();
            }





            if (rtmpopt.list_probaseline.Count > 2)// Calculating loop
            {

                rtmpopt.list_moloop = moloop.searchloop(rtmpopt.list_probaseline);

                for (int i = 0; i < rtmpopt.list_moloop.Count(); i++)
                {
                    rtmpopt.list_moloop[i].fs = Math.Sqrt(rtmpopt.list_moloop[i].fneu.X * rtmpopt.list_moloop[i].fneu.X + rtmpopt.list_moloop[i].fneu.Y * rtmpopt.list_moloop[i].fneu.Y + rtmpopt.list_moloop[i].fneu.Z * rtmpopt.list_moloop[i].fneu.Z);
                    rtmpopt.list_moloop[i].length = 0;
                    for (int j = 0; j < rtmpopt.list_moloop[i].listmobaseline.Count(); j++)
                    {
                        rtmpopt.list_moloop[i].length = rtmpopt.list_moloop[i].length + rtmpopt.list_moloop[i].listmobaseline[j].length;
                    }
                    rtmpopt.list_moloop[i].ppm = 1.0 / (rtmpopt.list_moloop[i].fs / rtmpopt.list_moloop[i].length);
                }


            }

            // Network Adjustment//////////////////////////////////////////////////////////////
            // Copyright by Peter Duong. Ph.D
            // Licensed by Aitogy., JSC
            // Generate a list of adjusted point

            //List<mopoint> list_adjpoint = new List<mopoint>();
            //List<mopoint> list_fixpoint = new List<mopoint>();
            //this.tSTB_Timeleft.Text = "Processing Adjustment..";
            for (int i = 0; i < rtmpopt.list_mopoint.Count; i++)
            {
                if (rtmpopt.list_mopoint[i].fix != true)
                    rtmpopt.list_adjpoint.Add(rtmpopt.list_mopoint[i]);
                else
                {
                    rtmpopt.list_fixpoint.Add(rtmpopt.list_mopoint[i]);

                }
            }

          
            for (int i = 0; i < rtmpopt.list_probaseline.Count; i++)
            {
                if (rtmpopt.list_probaseline[i].hstd < rtmpopt.hstd_thres && rtmpopt.list_probaseline[i].std.Z < rtmpopt.vstd_thres)
                {

                    rtmpopt.list_adjbaseline.Add(rtmpopt.list_probaseline[i]);
                }


            }
            //initialize matrice
            int nb = rtmpopt.list_adjbaseline.Count() * 3;
            int np = rtmpopt.list_adjpoint.Count() * 3;
            rtmpopt.V = new double[nb];
            if (nb > np)
            {
                double[][] matrixA = pmatrix.MatrixCreate(nb, np);
                double[][] matrixP = pmatrix.MatrixCreate(nb, nb);
                double[] matrixL = new double[nb];
                //double[,] matrixR = new double[np, np];
                //double[] matrixX = new double[np];
                //double[] matrixV = new double[nb];
                // Generate matrix A, P, L
                double ref_C = Math.Pow(rtmpopt.ref_scale, 2);
                for (int i = 0; i < rtmpopt.list_adjbaseline.Count(); i++)
                {
                    for (int j = 0; j < rtmpopt.list_adjpoint.Count(); j++)
                    {

                        if (rtmpopt.list_adjbaseline[i].vector[0] == rtmpopt.list_adjpoint[j])
                        {
                            matrixA[i * 3][j * 3] = -1.0;
                            matrixA[i * 3 + 1][j * 3 + 1] = -1.0;
                            matrixA[i * 3 + 2][j * 3 + 2] = -1.0;
                            matrixL[i * 3] = (rtmpopt.list_adjbaseline[i].vector[1].Appneu.X - rtmpopt.list_adjbaseline[i].vector[0].Appneu.X) - rtmpopt.list_adjbaseline[i].dneu.X;
                            matrixL[i * 3 + 1] = (rtmpopt.list_adjbaseline[i].vector[1].Appneu.Y - rtmpopt.list_adjbaseline[i].vector[0].Appneu.Y) - rtmpopt.list_adjbaseline[i].dneu.Y;
                            matrixL[i * 3 + 2] = (rtmpopt.list_adjbaseline[i].vector[1].Appneu.Z - rtmpopt.list_adjbaseline[i].vector[0].Appneu.Z) - rtmpopt.list_adjbaseline[i].dneu.Z;
                            matrixP[i * 3][i * 3] = ref_C / (rtmpopt.list_adjbaseline[i].std.X * rtmpopt.list_adjbaseline[i].std.X + 0.00000001);
                            matrixP[i * 3 + 1][i * 3 + 1] = ref_C / (rtmpopt.list_adjbaseline[i].std.Y * rtmpopt.list_adjbaseline[i].std.Y + 0.00000001);
                            matrixP[i * 3 + 2][i * 3 + 2] = ref_C / (rtmpopt.list_adjbaseline[i].std.Z * rtmpopt.list_adjbaseline[i].std.Z + 0.00000001);
                            //break;

                        }
                        else if (rtmpopt.list_adjbaseline[i].vector[1] == rtmpopt.list_adjpoint[j])
                        {
                            matrixA[i * 3][j * 3] = 1.0;
                            matrixA[i * 3 + 1][j * 3 + 1] = 1.0;
                            matrixA[i * 3 + 2][j * 3 + 2] = 1.0;
                            matrixL[i * 3] = (rtmpopt.list_adjbaseline[i].vector[1].Appneu.X - rtmpopt.list_adjbaseline[i].vector[0].Appneu.X) - rtmpopt.list_adjbaseline[i].dneu.X;
                            matrixL[i * 3 + 1] = (rtmpopt.list_adjbaseline[i].vector[1].Appneu.Y - rtmpopt.list_adjbaseline[i].vector[0].Appneu.Y) - rtmpopt.list_adjbaseline[i].dneu.Y;
                            matrixL[i * 3 + 2] = (rtmpopt.list_adjbaseline[i].vector[1].Appneu.Z - rtmpopt.list_adjbaseline[i].vector[0].Appneu.Z) - rtmpopt.list_adjbaseline[i].dneu.Z;
                            matrixP[i * 3][i * 3] = ref_C / (rtmpopt.list_adjbaseline[i].std.X * rtmpopt.list_adjbaseline[i].std.X + 0.00000001);
                            matrixP[i * 3 + 1][i * 3 + 1] = ref_C / (rtmpopt.list_adjbaseline[i].std.Y * rtmpopt.list_adjbaseline[i].std.Y + 0.00000001);
                            matrixP[i * 3 + 2][i * 3 + 2] = ref_C / (rtmpopt.list_adjbaseline[i].std.Z * rtmpopt.list_adjbaseline[i].std.Z + 0.00000001);
                            //break;
                        }
                    }
                }
                //Generating matrix R, b, Q
                double[][] At = pmatrix.Transpose(matrixA);
                At = pmatrix.MatrixProduct(At, matrixP);
                double[][] R = pmatrix.MatrixProduct(At, matrixA);
                double[] b = pmatrix.MatrixVectorProduct(At, matrixL);
                //double a = pmatrix.MatrixDeterminant(R);
                //Matrix Ppre = Matrix.Diag(b);
                //if (a != 0)
                //{
                double[][] Q = pmatrix.MatrixInverse(R);
                double[] X = pmatrix.MatrixVectorProduct(Q, b);
                for (int i = 0; i < X.Count(); i++) X[i] = -X[i];
                double[] AX = pmatrix.MatrixVectorProduct(matrixA, X);

                //calculate residual
                for (int i = 0; i < nb; i++)
                {
                    rtmpopt.V[i] = AX[i] + matrixL[i];
                }
                // calculate adjusted baseline

                for (int i = 0; i < rtmpopt.list_adjbaseline.Count(); i++)
                {

                    rtmpopt.list_adjbaseline[i].dneu.X = rtmpopt.list_adjbaseline[i].dneu.X + rtmpopt.V[i * 3];
                    rtmpopt.list_adjbaseline[i].dneu.Y = rtmpopt.list_adjbaseline[i].dneu.Y + rtmpopt.V[i * 3 + 1];
                    rtmpopt.list_adjbaseline[i].dneu.Z = rtmpopt.list_adjbaseline[i].dneu.Z + rtmpopt.V[i * 3 + 2];

                }
                // check adjusted loops
                rtmpopt.list_proloop = moloop.searchloop(rtmpopt.list_adjbaseline);

                for (int i = 0; i < rtmpopt.list_proloop.Count(); i++)
                {
                    rtmpopt.list_proloop[i].fs = Math.Sqrt(rtmpopt.list_proloop[i].fneu.X * rtmpopt.list_proloop[i].fneu.X + rtmpopt.list_proloop[i].fneu.Y * rtmpopt.list_proloop[i].fneu.Y + rtmpopt.list_proloop[i].fneu.Z * rtmpopt.list_proloop[i].fneu.Z);
                    rtmpopt.list_proloop[i].length = 0;
                    for (int j = 0; j < rtmpopt.list_proloop[i].listmobaseline.Count(); j++)
                    {
                        rtmpopt.list_proloop[i].length = rtmpopt.list_proloop[i].length + rtmpopt.list_proloop[i].listmobaseline[j].length;
                    }
                    rtmpopt.list_proloop[i].ppm = 1.0 / (rtmpopt.list_proloop[i].fs / rtmpopt.list_proloop[i].length);
                }

                // Calculate adjusted points.

                for (int i = 0; i < rtmpopt.list_adjpoint.Count(); i++)
                {

                    rtmpopt.list_adjpoint[i].Adjneu.X = rtmpopt.list_adjpoint[i].Appneu.X + X[i * 3];// +Math.Pow(-1.0, Convert.ToDouble(rtmpopt.iniround)) / (rtmpopt.cur_time + 100) + (i + 1) / 100.0;
                    rtmpopt.list_adjpoint[i].Adjneu.Y = rtmpopt.list_adjpoint[i].Appneu.Y + X[i * 3 + 1];// +Math.Pow(-1.0, Convert.ToDouble(rtmpopt.iniround + 1)) / (rtmpopt.cur_time + 100) + (i + 1) / 70.0; 
                    rtmpopt.list_adjpoint[i].Adjneu.Z = rtmpopt.list_adjpoint[i].Appneu.Z + X[i * 3 + 2];// + Math.Pow(-1.0, Convert.ToDouble(rtmpopt.iniround)) /(rtmpopt.cur_time+100)+ (i+1)/50.0;

                }
                // Calculate reference factor
                double rf = 0;
                for (int i = 0; i < nb; i++) rf = rf + matrixP[i][i] * rtmpopt.V[i] * rtmpopt.V[i];
                double dof = nb - np;
                rf = Math.Sqrt(rf / dof);
                rtmpopt.ref_std = rf;
                // calculate adjusted point std

                for (int i = 0; i < rtmpopt.list_adjpoint.Count(); i++)
                {
                    rtmpopt.list_adjpoint[i].std.X = rf * Math.Sqrt(Q[i * 3][i * 3]);
                    rtmpopt.list_adjpoint[i].std.Y = rf * Math.Sqrt(Q[i * 3 + 1][i * 3 + 1]);
                    rtmpopt.list_adjpoint[i].std.Z = rf * Math.Sqrt(Q[i * 3 + 2][i * 3 + 2]);
                }

                //}
                //Report results

            }
            else
            {
                for (int i = 0; i < rtmpopt.list_adjpoint.Count(); i++)
                {

                    rtmpopt.list_adjpoint[i].Adjneu.X = rtmpopt.list_adjpoint[i].Appneu.X;// +Math.Pow(-1.0, Convert.ToDouble(rtmpopt.iniround)) / (rtmpopt.cur_time + 100) + i / 100;
                    rtmpopt.list_adjpoint[i].Adjneu.Y = rtmpopt.list_adjpoint[i].Appneu.Y;// +Math.Pow(-1.0, Convert.ToDouble(rtmpopt.iniround + 1)) / (rtmpopt.cur_time + 100) + i / 70;
                    rtmpopt.list_adjpoint[i].Adjneu.Z = rtmpopt.list_adjpoint[i].Appneu.Z;// +Math.Pow(-1.0, Convert.ToDouble(rtmpopt.iniround)) / (rtmpopt.cur_time + 100) + i / 20;

                }
            }

           


            //rtmp_opt.print_to_file(mainForm.globalvar.reportfile, rtmpopt);
            //rtmpopt.send_adjust_to_mqtt();
            rtmpopt.Print_report_tofile();
            Process.Start(rtmpopt.reportfile);

        }

        public static void GNSS_data_processing(rtmp_opt rtmpopt, List<mopoint> list_mopoint, C_Datum datum, int mode)
        {

           
            //rtmpopt.list_mopoint = new List<mopoint>();
            rtmpopt.list_fixpoint = new List<mopoint>();
            rtmpopt.list_adjpoint = new List<mopoint>();
            rtmpopt.list_moloop = new List<moloop>();
            rtmpopt.list_proloop = new List<moloop>();
            rtmpopt.list_mobaseline = new List<mobaseline>();
            rtmpopt.list_passedmobaseline = new List<mobaseline>();
            rtmpopt.list_probaseline = new List<mobaseline>();
            rtmpopt.list_adjbaseline = new List<mobaseline>();
            rtmpopt.report_flag = true;
            base_t[] m_base = new base_t[1];
            rtmpopt.backward = true;

            if (rtmpopt.list_mopoint.Count < 1)
            {
                return;
            }

            DateTime now = DateTime.Now;
            string starday = now.Year.ToString() + "_" + now.Month.ToString() + "_" + now.Day.ToString();
            string dayfolder = rtmpopt.list_mopoint[0].pathname + "\\" + starday;
            if (System.IO.Directory.Exists(dayfolder) == false)
                try
                {
                    System.IO.Directory.CreateDirectory(dayfolder);
                }
                catch { return; }



            string startime = now.Year.ToString() + "_" + now.Month.ToString() + "_" + now.Day.ToString() + "_" + now.Hour.ToString() + "_" + now.Minute.ToString();
            rtmpopt.reportfile = dayfolder + "\\" + startime + "_Adjust" + ".txt";
            //mainForm.globalvar.reportfile = rtmpopt.list_mopoint[0].pathname + "\\report.xml";
            StreamWriter logfile = new System.IO.StreamWriter(rtmpopt.list_mopoint[0].pathname + "\\logfile.txt");

            if (rtmpopt.nfix == 0)//Nếu không có điểm gốc nào thì lấy điểm quan trắc đầu tiên làm gốc
            {


                rtmpopt.list_mopoint[0].fix = true;

                if (mopoint.get_AppXYH_fromSpp(rtmpopt.list_mopoint[0], datum) > 0)
                {
                    rtmpopt.list_mopoint[0].processed = true;
                    rtmpopt.list_mopoint[0].pos_opt = 3;
                }
                else if (mopoint.get_AppXYH_fromRNX_header(rtmpopt.list_mopoint[0], datum) > 0)
                {
                    rtmpopt.list_mopoint[0].processed = true;
                    rtmpopt.list_mopoint[0].pos_opt = 4;
                }
                else
                {
                    return; //Nếu không có điểm gốc nào thì thoát chương trình
                }


            }

            //starting conversion to rinex
            if (mode == 1)//.rtc
            {
                for (int i = 0; i < rtmpopt.list_mopoint.Count; i++)// Convert data to RINEX
                {
                    if (rtmpopt.list_mopoint[i].rtk_mode < 2)
                    {
                        int iDeviceId = 0;
                        string sDeviceId = System.IO.Path.GetFileNameWithoutExtension(rtmpopt.list_mopoint[i].datafile);
                        var bDeviceId = int.TryParse(sDeviceId, out iDeviceId);



                        rtmpopt.list_mopoint[i].convert2rinex();




                    }
                }
            }

            for (int i = 0; i < rtmpopt.list_mopoint.Count; i++)// Generating baseline list
                for (int j = i + 1; j < rtmpopt.list_mopoint.Count; j++)
                {
                    mobaseline baseline = new mobaseline();
                    baseline.frompoint = baseline.vector[0] = rtmpopt.list_mopoint[i];
                    baseline.topoint = baseline.vector[1] = rtmpopt.list_mopoint[j];
                    //baseline.resultfile=
                    mobaseline.get_resultfile(baseline);
                    rtmpopt.list_mobaseline.Add(baseline);
                    logfile.WriteLine(logfile.NewLine + "Baseline: " + baseline.frompoint.name + " to " + baseline.topoint.name + " file: " + baseline.resultfile);
                }
           



            ///////////////////////Bắt đầu xử lý bình sai
            int nbp = 0;
            for (int i = 0; i < rtmpopt.list_mobaseline.Count; i++) // Baseline Processing
            {


                if (rtmpopt.list_mobaseline[i].vector[0].rtk_mode == 2 && rtmpopt.list_mobaseline[i].vector[1].rtk_mode == 1)
                {
                    rtmpopt.list_mobaseline[i].dneu.X = rtmpopt.list_mobaseline[i].vector[1].rtkmeas.dN;
                    rtmpopt.list_mobaseline[i].dneu.Y = rtmpopt.list_mobaseline[i].vector[1].rtkmeas.dE;
                    rtmpopt.list_mobaseline[i].dneu.Z = rtmpopt.list_mobaseline[i].vector[1].rtkmeas.dU;
                    rtmpopt.list_mobaseline[i].length = Math.Sqrt(rtmpopt.list_mobaseline[i].dneu.X * rtmpopt.list_mobaseline[i].dneu.X + rtmpopt.list_mobaseline[i].dneu.Y * rtmpopt.list_mobaseline[i].dneu.Y + rtmpopt.list_mobaseline[i].dneu.Z * rtmpopt.list_mobaseline[i].dneu.Z);
                    rtmpopt.list_mobaseline[i].std.X = rtmpopt.list_mobaseline[i].vector[1].rtkmeas.aN;
                    rtmpopt.list_mobaseline[i].std.Y = rtmpopt.list_mobaseline[i].vector[1].rtkmeas.aE;
                    rtmpopt.list_mobaseline[i].std.Z = rtmpopt.list_mobaseline[i].vector[1].rtkmeas.aU;
                    rtmpopt.list_mobaseline[i].hstd = Math.Sqrt(rtmpopt.list_mobaseline[i].std.X * rtmpopt.list_mobaseline[i].std.X + rtmpopt.list_mobaseline[i].std.Y * rtmpopt.list_mobaseline[i].std.Y);
                    rtmpopt.list_mobaseline[i].ratio = 10.0 - 2 * rtmpopt.list_mobaseline[i].length * 0.000001;
                    if (rtmpopt.list_mobaseline[i].vector[0].processed == true && rtmpopt.list_mobaseline[i].vector[1].processed == false)
                    {
                        rtmpopt.list_mobaseline[i].vector[1].Appneu = Point3D.plus(rtmpopt.list_mobaseline[i].vector[0].Appneu, rtmpopt.list_mobaseline[i].dneu);
                        rtmpopt.list_mobaseline[i].vector[1].std = Point3D.plus_std(rtmpopt.list_mobaseline[i].vector[0].std, rtmpopt.list_mobaseline[i].std);
                        rtmpopt.list_mobaseline[i].vector[1].processed = true;
                    }
                    else if (rtmpopt.list_mobaseline[i].vector[0].processed == false && rtmpopt.list_mobaseline[i].vector[1].processed == true)
                    {
                        rtmpopt.list_mobaseline[i].vector[0].Appneu = Point3D.minus(rtmpopt.list_mobaseline[i].vector[1].Appneu, rtmpopt.list_mobaseline[i].dneu);
                        rtmpopt.list_mobaseline[i].vector[0].std = Point3D.plus_std(rtmpopt.list_mobaseline[i].vector[1].std, rtmpopt.list_mobaseline[i].std);
                        rtmpopt.list_mobaseline[i].vector[0].processed = true;
                    }
                    rtmpopt.list_mobaseline[i].processed = 1;
                    rtmpopt.list_probaseline.Add(rtmpopt.list_mobaseline[i]);

                    rtmpopt.list_mobaseline[i].vector[1].rtkmeas.nstatic_update = 0;
                    rtmpopt.list_mobaseline[i].vector[1].rtkmeas.W.X = 0.0;
                    rtmpopt.list_mobaseline[i].vector[1].rtkmeas.W.Y = 0.0;
                    rtmpopt.list_mobaseline[i].vector[1].rtkmeas.W.Z = 0.0;
                    rtmpopt.list_mobaseline[i].vector[1].rtkmeas.S.X = 0.0;
                    rtmpopt.list_mobaseline[i].vector[1].rtkmeas.S.Y = 0.0;
                    rtmpopt.list_mobaseline[i].vector[1].rtkmeas.S.Z = 0.0;
                    nbp++;

                }
                else if (rtmpopt.list_mobaseline[i].vector[0].rtk_mode == 1 && rtmpopt.list_mobaseline[i].vector[1].rtk_mode == 2)
                {
                    rtmpopt.list_mobaseline[i].dneu.X = rtmpopt.list_mobaseline[i].vector[0].rtkmeas.dN;
                    rtmpopt.list_mobaseline[i].dneu.Y = rtmpopt.list_mobaseline[i].vector[0].rtkmeas.dE;
                    rtmpopt.list_mobaseline[i].dneu.Z = rtmpopt.list_mobaseline[i].vector[0].rtkmeas.dU;
                    rtmpopt.list_mobaseline[i].length = Math.Sqrt(rtmpopt.list_mobaseline[i].dneu.X * rtmpopt.list_mobaseline[i].dneu.X + rtmpopt.list_mobaseline[i].dneu.Y * rtmpopt.list_mobaseline[i].dneu.Y + rtmpopt.list_mobaseline[i].dneu.Z * rtmpopt.list_mobaseline[i].dneu.Z);
                    rtmpopt.list_mobaseline[i].std.X = rtmpopt.list_mobaseline[i].vector[0].rtkmeas.aN;
                    rtmpopt.list_mobaseline[i].std.Y = rtmpopt.list_mobaseline[i].vector[0].rtkmeas.aE;
                    rtmpopt.list_mobaseline[i].std.Z = rtmpopt.list_mobaseline[i].vector[0].rtkmeas.aU;
                    rtmpopt.list_mobaseline[i].hstd = Math.Sqrt(rtmpopt.list_mobaseline[i].std.X * rtmpopt.list_mobaseline[i].std.X + rtmpopt.list_mobaseline[i].std.Y * rtmpopt.list_mobaseline[i].std.Y);
                    rtmpopt.list_mobaseline[i].ratio = 10.0 - 2 * rtmpopt.list_mobaseline[i].length * 0.000001;
                    if (rtmpopt.list_mobaseline[i].vector[0].processed == true && rtmpopt.list_mobaseline[i].vector[1].processed == false)
                    {
                        rtmpopt.list_mobaseline[i].vector[1].Appneu = Point3D.plus(rtmpopt.list_mobaseline[i].vector[0].Appneu, rtmpopt.list_mobaseline[i].dneu);
                        rtmpopt.list_mobaseline[i].vector[1].std = Point3D.plus_std(rtmpopt.list_mobaseline[i].vector[0].std, rtmpopt.list_mobaseline[i].std);
                        rtmpopt.list_mobaseline[i].vector[1].processed = true;
                    }
                    else if (rtmpopt.list_mobaseline[i].vector[0].processed == false && rtmpopt.list_mobaseline[i].vector[1].processed == true)
                    {
                        rtmpopt.list_mobaseline[i].vector[0].Appneu = Point3D.minus(rtmpopt.list_mobaseline[i].vector[1].Appneu, rtmpopt.list_mobaseline[i].dneu);
                        rtmpopt.list_mobaseline[i].vector[0].std = Point3D.plus_std(rtmpopt.list_mobaseline[i].vector[1].std, rtmpopt.list_mobaseline[i].std);
                        rtmpopt.list_mobaseline[i].vector[0].processed = true;
                    }

                    rtmpopt.list_mobaseline[i].processed = 1;
                    rtmpopt.list_probaseline.Add(rtmpopt.list_mobaseline[i]);
                    rtmpopt.list_mobaseline[i].vector[0].rtkmeas.nstatic_update = 0;
                    rtmpopt.list_mobaseline[i].vector[0].rtkmeas.W.X = 0.0;
                    rtmpopt.list_mobaseline[i].vector[0].rtkmeas.W.Y = 0.0;
                    rtmpopt.list_mobaseline[i].vector[0].rtkmeas.W.Z = 0.0;
                    rtmpopt.list_mobaseline[i].vector[0].rtkmeas.S.X = 0.0;
                    rtmpopt.list_mobaseline[i].vector[0].rtkmeas.S.Y = 0.0;
                    rtmpopt.list_mobaseline[i].vector[0].rtkmeas.S.Z = 0.0;
                    nbp++;
                }
                else if (rtmpopt.list_mobaseline[i].vector[0].rtk_mode < 2 && rtmpopt.list_mobaseline[i].vector[1].rtk_mode < 2)
                {
                    if (System.IO.File.Exists(rtmpopt.list_mobaseline[i].vector[0].obsname) == true && System.IO.File.Exists(rtmpopt.list_mobaseline[i].vector[1].obsname) == true)
                    {////Calculate Baseline from raw data
                        String exePath = System.Windows.Forms.Application.StartupPath;
                        String aipos = exePath + "\\rnx2rtkp.exe";
                        String navfile = "";
                        if (rtmpopt.aipos_version == 1)
                        {
                            aipos = exePath + "\\rnx2rtkp.exe";
                        }
                        long minnavesize = 4;
                        for (int k = 0; k < list_mopoint.Count; k++)
                        {
                            if (System.IO.File.Exists(list_mopoint[k].navname) && new System.IO.FileInfo(list_mopoint[k].navname).Length > minnavesize)
                            {
                                navfile = list_mopoint[k].navname;
                                minnavesize = new System.IO.FileInfo(navfile).Length;
                            }
                        }
                        String favoPath = Environment.GetFolderPath(System.Environment.SpecialFolder.Favorites) + "\\aibase";
                        String cfgfile = favoPath + "\\Static.conf";
                        //String arg = "-v " + RNXVER + " -r ubx" + " -o " + textObs.Text + " -n " + textNav.Text + " " + textInput.Text;
                        String arg = "-k " + cfgfile + " -o " + rtmpopt.list_mobaseline[i].resultfile + " " + rtmpopt.list_mobaseline[i].vector[1].obsname + " " + rtmpopt.list_mobaseline[i].vector[0].obsname + " " + navfile;
                        String barg = "-k " + cfgfile + " -o " + rtmpopt.list_mobaseline[i].bresultfile + " " + rtmpopt.list_mobaseline[i].vector[0].obsname + " " + rtmpopt.list_mobaseline[i].vector[1].obsname + " " + navfile;


                        Process aip = new Process();
                        aip.StartInfo.FileName = aipos;
                        aip.StartInfo.Arguments = arg;
                        aip.StartInfo.UseShellExecute = true;        // BẮT BUỘC
                        aip.EnableRaisingEvents = true;
                        //aip.StartInfo.Verb = "runas";
                        //aip.StartInfo.WindowStyle = ProcessWindowStyle.Hidden;


                        try
                        {

                            //logfile.WriteLine(logfile.NewLine + "Processing baseline: " + rtmpopt.list_mobaseline[i].frompoint.name + " to " + rtmpopt.list_mobaseline[i].topoint.name + " command: " + aipos + " " + arg);
                            aip.Start();
                            // this.tSTB_Timeleft.Text = "Processing baseline " + (i + 1).ToString() + "/" + rtmpopt.list_mobaseline.Count.ToString();

                            aip.WaitForExit();
                            aip.Close();
                            if (System.IO.File.Exists(rtmpopt.list_mobaseline[i].resultfile) == true)
                            {
                                nbp = nbp + mobaseline.get_result(rtmpopt.list_mobaseline[i], rtmpopt.ratio_thres,datum,rtmpopt);
                                logfile.WriteLine(logfile.NewLine + "Baseline processed fw: " + rtmpopt.list_mobaseline[i].frompoint.name + " to " + rtmpopt.list_mobaseline[i].topoint.name + " length: " + rtmpopt.list_mobaseline[i].length.ToString("F3") + " ratio: " + rtmpopt.list_mobaseline[i].ratio.ToString("F3"));
                            }


                        }
                        catch
                        {
                            //MessageBox.Show("Something wrong in processing baseline!");
                        }
                        if (rtmpopt.backward == true)
                        {
                            aip.StartInfo.Arguments = barg;
                            try
                            {

                                //Process.Start(convbin, conarg);
                                aip.Start();
                                aip.WaitForExit();
                                aip.Close();
                                if (System.IO.File.Exists(rtmpopt.list_mobaseline[i].bresultfile) == true)
                                {
                                    nbp = nbp + mobaseline.get_bresult(rtmpopt.list_mobaseline[i], rtmpopt.ratio_thres,datum,rtmpopt);
                                    logfile.WriteLine(logfile.NewLine + "Baseline processed bw: " + rtmpopt.list_mobaseline[i].topoint.name + " to " + rtmpopt.list_mobaseline[i].frompoint.name + " length: " + rtmpopt.list_mobaseline[i].length.ToString("F3") + " ratio: " + rtmpopt.list_mobaseline[i].ratio.ToString("F3"));
                                }

                            }
                            catch
                            {
                                //MessageBox.Show("Something wrong in processing baseline!");
                                //return;
                            }

                        }
                    }


                }


            }

            //calculating approximate point
            if (rtmpopt.list_probaseline.Count > 0)
            {
                rtmpopt.tmp_String = new System.IO.StringWriter();
                rtmpopt.print_Baseline_to_String();
            }





            if (nbp > 2)// Calculating loop
            {

                rtmpopt.list_moloop = moloop.searchloop(rtmpopt.list_probaseline);

                for (int i = 0; i < rtmpopt.list_moloop.Count(); i++)
                {
                    rtmpopt.list_moloop[i].fs = Math.Sqrt(rtmpopt.list_moloop[i].fneu.X * rtmpopt.list_moloop[i].fneu.X + rtmpopt.list_moloop[i].fneu.Y * rtmpopt.list_moloop[i].fneu.Y + rtmpopt.list_moloop[i].fneu.Z * rtmpopt.list_moloop[i].fneu.Z);
                    rtmpopt.list_moloop[i].length = 0;
                    for (int j = 0; j < rtmpopt.list_moloop[i].listmobaseline.Count(); j++)
                    {
                        rtmpopt.list_moloop[i].length = rtmpopt.list_moloop[i].length + rtmpopt.list_moloop[i].listmobaseline[j].length;
                    }
                    rtmpopt.list_moloop[i].ppm = 1.0 / (rtmpopt.list_moloop[i].fs / rtmpopt.list_moloop[i].length);

                    //if (rtmpopt.list_moloop[i].ppm > rtmpopt.ppm_theres)
                    //{
                    //    rtmpopt.report_flag = false;
                    //    return;
                    //}

                }


            }

            // Network Adjustment//////////////////////////////////////////////////////////////
            // Copyright by Peter Duong. Ph.D
            // Licensed by Aitogy., JSC
            // Generate a list of adjusted point

            //List<mopoint> list_adjpoint = new List<mopoint>();
            //List<mopoint> list_fixpoint = new List<mopoint>();
            //this.tSTB_Timeleft.Text = "Processing Adjustment..";
            for (int i = 0; i < rtmpopt.list_mopoint.Count; i++)
            {
                if (System.IO.File.Exists(list_mopoint[i].obsname) == true && rtmpopt.list_mopoint[i].fix != true)
                    rtmpopt.list_adjpoint.Add(rtmpopt.list_mopoint[i]);
                else
                {
                    rtmpopt.list_fixpoint.Add(rtmpopt.list_mopoint[i]);

                }
            }

          
           
            ////Remove low quality baseline before adjustment
         
            for (int i = 0; i < rtmpopt.list_probaseline.Count; i++)
            {
                if (rtmpopt.list_probaseline[i].hstd < rtmpopt.hstd_thres && rtmpopt.list_probaseline[i].std.Z < rtmpopt.vstd_thres)
                {

                    rtmpopt.list_adjbaseline.Add(rtmpopt.list_probaseline[i]);
                }


            }
            //initialize matrice
            int nb = rtmpopt.list_adjbaseline.Count() * 3;
            int np = rtmpopt.list_adjpoint.Count() * 3;
            rtmpopt.V = new double[nb];
            if (nb > np)
            {
                double[][] matrixA = pmatrix.MatrixCreate(nb, np);
                double[][] matrixP = pmatrix.MatrixCreate(nb, nb);
                double[] matrixL = new double[nb];
                double ref_C = Math.Pow(rtmpopt.ref_scale, 2);
                for (int i = 0; i < rtmpopt.list_adjbaseline.Count(); i++)
                {
                    for (int j = 0; j < rtmpopt.list_adjpoint.Count(); j++)
                    {

                        if (rtmpopt.list_adjbaseline[i].vector[0] == rtmpopt.list_adjpoint[j])
                        {
                            matrixA[i * 3][j * 3] = -1.0;
                            matrixA[i * 3 + 1][j * 3 + 1] = -1.0;
                            matrixA[i * 3 + 2][j * 3 + 2] = -1.0;
                            matrixL[i * 3] = (rtmpopt.list_adjbaseline[i].vector[1].Appneu.X - rtmpopt.list_adjbaseline[i].vector[0].Appneu.X) - rtmpopt.list_adjbaseline[i].dneu.X;
                            matrixL[i * 3 + 1] = (rtmpopt.list_adjbaseline[i].vector[1].Appneu.Y - rtmpopt.list_adjbaseline[i].vector[0].Appneu.Y) - rtmpopt.list_adjbaseline[i].dneu.Y;
                            matrixL[i * 3 + 2] = (rtmpopt.list_adjbaseline[i].vector[1].Appneu.Z - rtmpopt.list_adjbaseline[i].vector[0].Appneu.Z) - rtmpopt.list_adjbaseline[i].dneu.Z;
                            matrixP[i * 3][i * 3] = ref_C / (rtmpopt.list_adjbaseline[i].std.X * rtmpopt.list_adjbaseline[i].std.X + 0.00000001);
                            matrixP[i * 3 + 1][i * 3 + 1] = ref_C / (rtmpopt.list_adjbaseline[i].std.Y * rtmpopt.list_adjbaseline[i].std.Y + 0.00000001);
                            matrixP[i * 3 + 2][i * 3 + 2] = ref_C / (rtmpopt.list_adjbaseline[i].std.Z * rtmpopt.list_adjbaseline[i].std.Z + 0.00000001);
                            //break;

                        }
                        else if (rtmpopt.list_adjbaseline[i].vector[1] == rtmpopt.list_adjpoint[j])
                        {
                            matrixA[i * 3][j * 3] = 1.0;
                            matrixA[i * 3 + 1][j * 3 + 1] = 1.0;
                            matrixA[i * 3 + 2][j * 3 + 2] = 1.0;
                            matrixL[i * 3] = (rtmpopt.list_adjbaseline[i].vector[1].Appneu.X - rtmpopt.list_adjbaseline[i].vector[0].Appneu.X) - rtmpopt.list_adjbaseline[i].dneu.X;
                            matrixL[i * 3 + 1] = (rtmpopt.list_adjbaseline[i].vector[1].Appneu.Y - rtmpopt.list_adjbaseline[i].vector[0].Appneu.Y) - rtmpopt.list_adjbaseline[i].dneu.Y;
                            matrixL[i * 3 + 2] = (rtmpopt.list_adjbaseline[i].vector[1].Appneu.Z - rtmpopt.list_adjbaseline[i].vector[0].Appneu.Z) - rtmpopt.list_adjbaseline[i].dneu.Z;
                            matrixP[i * 3][i * 3] = ref_C / (rtmpopt.list_adjbaseline[i].std.X * rtmpopt.list_adjbaseline[i].std.X + 0.00000001);
                            matrixP[i * 3 + 1][i * 3 + 1] = ref_C / (rtmpopt.list_adjbaseline[i].std.Y * rtmpopt.list_adjbaseline[i].std.Y + 0.00000001);
                            matrixP[i * 3 + 2][i * 3 + 2] = ref_C / (rtmpopt.list_adjbaseline[i].std.Z * rtmpopt.list_adjbaseline[i].std.Z + 0.00000001);
                            //break;
                        }
                    }
                }
                //Generating matrix R, b, Q
                double[][] At = pmatrix.Transpose(matrixA);
                At = pmatrix.MatrixProduct(At, matrixP);
                double[][] R = pmatrix.MatrixProduct(At, matrixA);
                double[] b = pmatrix.MatrixVectorProduct(At, matrixL);
              
                double[][] Q = pmatrix.MatrixInverse(R);
                double[] X = pmatrix.MatrixVectorProduct(Q, b);
                for (int i = 0; i < X.Count(); i++) X[i] = -X[i];
                double[] AX = pmatrix.MatrixVectorProduct(matrixA, X);

                //calculate residual
                for (int i = 0; i < nb; i++)
                {
                    rtmpopt.V[i] = AX[i] + matrixL[i];
                }
                // calculate adjusted baseline

                for (int i = 0; i < rtmpopt.list_adjbaseline.Count(); i++)
                {

                    rtmpopt.list_adjbaseline[i].dneu.X = rtmpopt.list_adjbaseline[i].dneu.X + rtmpopt.V[i * 3];
                    rtmpopt.list_adjbaseline[i].dneu.Y = rtmpopt.list_adjbaseline[i].dneu.Y + rtmpopt.V[i * 3 + 1];
                    rtmpopt.list_adjbaseline[i].dneu.Z = rtmpopt.list_adjbaseline[i].dneu.Z + rtmpopt.V[i * 3 + 2];

                }
                // check adjusted loops
                rtmpopt.list_proloop = moloop.searchloop(rtmpopt.list_adjbaseline);

                for (int i = 0; i < rtmpopt.list_proloop.Count(); i++)
                {
                    rtmpopt.list_proloop[i].fs = Math.Sqrt(rtmpopt.list_proloop[i].fneu.X * rtmpopt.list_proloop[i].fneu.X + rtmpopt.list_proloop[i].fneu.Y * rtmpopt.list_proloop[i].fneu.Y + rtmpopt.list_proloop[i].fneu.Z * rtmpopt.list_proloop[i].fneu.Z);
                    rtmpopt.list_proloop[i].length = 0;
                    for (int j = 0; j < rtmpopt.list_proloop[i].listmobaseline.Count(); j++)
                    {
                        rtmpopt.list_proloop[i].length = rtmpopt.list_proloop[i].length + rtmpopt.list_proloop[i].listmobaseline[j].length;
                    }
                    rtmpopt.list_proloop[i].ppm = 1.0 / (rtmpopt.list_proloop[i].fs / rtmpopt.list_proloop[i].length);
                }

                // Calculate adjusted points.

                for (int i = 0; i < rtmpopt.list_adjpoint.Count(); i++)
                {

                    rtmpopt.list_adjpoint[i].Adjneu.X = rtmpopt.list_adjpoint[i].Appneu.X + X[i * 3];// +Math.Pow(-1.0, Convert.ToDouble(rtmpopt.iniround)) / (rtmpopt.cur_time + 100) + (i + 1) / 100.0;
                    rtmpopt.list_adjpoint[i].Adjneu.Y = rtmpopt.list_adjpoint[i].Appneu.Y + X[i * 3 + 1];// +Math.Pow(-1.0, Convert.ToDouble(rtmpopt.iniround + 1)) / (rtmpopt.cur_time + 100) + (i + 1) / 70.0; 
                    rtmpopt.list_adjpoint[i].Adjneu.Z = rtmpopt.list_adjpoint[i].Appneu.Z + X[i * 3 + 2];// + Math.Pow(-1.0, Convert.ToDouble(rtmpopt.iniround)) /(rtmpopt.cur_time+100)+ (i+1)/50.0;

                }
                // Calculate reference factor
                double rf = 0;
                for (int i = 0; i < nb; i++) rf = rf + matrixP[i][i] * rtmpopt.V[i] * rtmpopt.V[i];
                double dof = nb - np;
                rf = Math.Sqrt(rf / dof);
                rtmpopt.ref_std = rf;
                // calculate adjusted point std

                for (int i = 0; i < rtmpopt.list_adjpoint.Count(); i++)
                {
                    rtmpopt.list_adjpoint[i].std.X = rf * Math.Sqrt(Q[i * 3][i * 3]);
                    rtmpopt.list_adjpoint[i].std.Y = rf * Math.Sqrt(Q[i * 3 + 1][i * 3 + 1]);
                    rtmpopt.list_adjpoint[i].std.Z = rf * Math.Sqrt(Q[i * 3 + 2][i * 3 + 2]);
                }

                //}
                //Report results

            }
            else
            {
                for (int i = 0; i < rtmpopt.list_adjpoint.Count(); i++)
                {

                    rtmpopt.list_adjpoint[i].Adjneu.X = rtmpopt.list_adjpoint[i].Appneu.X;// +Math.Pow(-1.0, Convert.ToDouble(rtmpopt.iniround)) / (rtmpopt.cur_time + 100) + i / 100;
                    rtmpopt.list_adjpoint[i].Adjneu.Y = rtmpopt.list_adjpoint[i].Appneu.Y;// +Math.Pow(-1.0, Convert.ToDouble(rtmpopt.iniround + 1)) / (rtmpopt.cur_time + 100) + i / 70;
                    rtmpopt.list_adjpoint[i].Adjneu.Z = rtmpopt.list_adjpoint[i].Appneu.Z;// +Math.Pow(-1.0, Convert.ToDouble(rtmpopt.iniround)) / (rtmpopt.cur_time + 100) + i / 20;

                }
            }

           

            rtmpopt.cur_time = rtmpopt.iniround * rtmpopt.prc_interval;

            rtmpopt.Print_report_tofile();

            

            if (rtmpopt.clear_processed_data == true)
            {


                foreach (mobaseline baseline in rtmpopt.list_mobaseline)
                {
                    if (baseline.processed > 0)
                    {
                        if (System.IO.File.Exists(baseline.resultfile))
                            System.IO.File.Delete(baseline.resultfile);
                        if (System.IO.File.Exists(baseline.bresultfile))
                            System.IO.File.Delete(baseline.bresultfile);

                    }
                }


            }
            if (rtmpopt.data_from_file == false)
            {
                //Print_rtk_tofile();
            }
            //this.tSTB_Timeleft.Text = "Finish";
            logfile.Close();
            rtmpopt.iniround++;
            //tSL_Round.Text = rtmpopt.iniround.ToString();

        }
    }
}
