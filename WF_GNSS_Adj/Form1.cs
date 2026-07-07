using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Data;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace WF_GNSS_Adj
{
    public partial class Form1 : Form
    {
        List<String> obsfiles = new List<String>();
        List<String> navfiles = new List<String>();
        String Inputfile;
        public Form1()
        {
            InitializeComponent();
        }

        private void bnCancel_Click(object sender, EventArgs e)
        {
            this.Close();
        }

        private void bn_Input_Click(object sender, EventArgs e)
        {
            OpenFileDialog fDialog = new OpenFileDialog();
            fDialog.Title = "Open Input File";
            fDialog.Multiselect = true;
            fDialog.Filter = "OBS file(*.obs)|*.obs|NAV file(*.nav)|*.nav|All file(*.*)|*.*";
            //fDialog.RestoreDirectory = true;
            if (fDialog.ShowDialog() == DialogResult.OK)
            {
                //textBox1.Text = _openFileDialog.FileName;//đường dẫn của file trong textbo
                textInput.Text = fDialog.FileName;
                Inputfile = fDialog.FileName;
                System.IO.StreamReader infile = new System.IO.StreamReader(this.textInput.Text);
                if (infile == null)
                {
                    MessageBox.Show(" No output file, Please input one");
                    this.Close();
                }
                else
                {
                    String ImagePath = System.IO.Path.GetDirectoryName(this.textInput.Text);
                    string filename = System.IO.Path.GetFileNameWithoutExtension(this.textInput.Text);
                    foreach (var fn in fDialog.FileNames)
                    {
                        if (fn.Contains("obs"))
                        { obsfiles.Add(fn); }
                        if (fn.Contains("nav"))
                        { navfiles.Add(fn); }
                    }
                    
                    string f_kml;
                    f_kml = ImagePath + "\\" + filename + "kqbs.txt";
                    textOutput.Text = f_kml;

                    //int indexlong = comLong.SelectedIndex;// for checking index                    
                }
            }
        }

        private void bnProcess_Click(object sender, EventArgs e)
        {
            rtmp_opt rtmpopt=new rtmp_opt();
            C_Datum datum = new C_Datum();
            if (this.cB_InputType.SelectedIndex == 2)
            {
                rtmpopt.reportfile = this.textOutput.Text;
                Adj.GNSS_data_processing_FromFile(textInput.Text, 0,datum,rtmpopt);
                return;
            }
                     
        }
    }
}
