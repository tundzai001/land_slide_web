namespace WF_GNSS_Adj
{
    partial class Form1
    {
        /// <summary>
        /// Required designer variable.
        /// </summary>
        private System.ComponentModel.IContainer components = null;

        /// <summary>
        /// Clean up any resources being used.
        /// </summary>
        /// <param name="disposing">true if managed resources should be disposed; otherwise, false.</param>
        protected override void Dispose(bool disposing)
        {
            if (disposing && (components != null))
            {
                components.Dispose();
            }
            base.Dispose(disposing);
        }

        #region Windows Form Designer generated code

        /// <summary>
        /// Required method for Designer support - do not modify
        /// the contents of this method with the code editor.
        /// </summary>
        private void InitializeComponent()
        {
            this.cB_InputType = new System.Windows.Forms.ComboBox();
            this.lb_InputType = new System.Windows.Forms.Label();
            this.bnCancel = new System.Windows.Forms.Button();
            this.bn_option = new System.Windows.Forms.Button();
            this.bnProcess = new System.Windows.Forms.Button();
            this.bnOutput = new System.Windows.Forms.Button();
            this.bn_Input = new System.Windows.Forms.Button();
            this.textOutput = new System.Windows.Forms.TextBox();
            this.textInput = new System.Windows.Forms.TextBox();
            this.lb_outputfile = new System.Windows.Forms.Label();
            this.lb_Inputdata = new System.Windows.Forms.Label();
            this.SuspendLayout();
            // 
            // cB_InputType
            // 
            this.cB_InputType.FormattingEnabled = true;
            this.cB_InputType.Items.AddRange(new object[] {
            "RINEX data",
            "RTCM data",
            "FromFile data"});
            this.cB_InputType.Location = new System.Drawing.Point(81, 12);
            this.cB_InputType.Name = "cB_InputType";
            this.cB_InputType.Size = new System.Drawing.Size(350, 21);
            this.cB_InputType.TabIndex = 45;
            // 
            // lb_InputType
            // 
            this.lb_InputType.AutoSize = true;
            this.lb_InputType.Location = new System.Drawing.Point(11, 18);
            this.lb_InputType.Name = "lb_InputType";
            this.lb_InputType.Size = new System.Drawing.Size(63, 15);
            this.lb_InputType.TabIndex = 44;
            this.lb_InputType.Text = "Input Type";
            // 
            // bnCancel
            // 
            this.bnCancel.Location = new System.Drawing.Point(316, 158);
            this.bnCancel.Name = "bnCancel";
            this.bnCancel.Size = new System.Drawing.Size(78, 25);
            this.bnCancel.TabIndex = 41;
            this.bnCancel.Text = "Thoát";
            this.bnCancel.UseVisualStyleBackColor = true;
            this.bnCancel.Click += new System.EventHandler(this.bnCancel_Click);
            // 
            // bn_option
            // 
            this.bn_option.Location = new System.Drawing.Point(450, 158);
            this.bn_option.Name = "bn_option";
            this.bn_option.Size = new System.Drawing.Size(78, 25);
            this.bn_option.TabIndex = 42;
            this.bn_option.Text = "Option";
            this.bn_option.UseVisualStyleBackColor = true;
            // 
            // bnProcess
            // 
            this.bnProcess.Location = new System.Drawing.Point(110, 158);
            this.bnProcess.Name = "bnProcess";
            this.bnProcess.Size = new System.Drawing.Size(78, 25);
            this.bnProcess.TabIndex = 43;
            this.bnProcess.Text = "Xử lý";
            this.bnProcess.UseVisualStyleBackColor = true;
            this.bnProcess.Click += new System.EventHandler(this.bnProcess_Click);
            // 
            // bnOutput
            // 
            this.bnOutput.Location = new System.Drawing.Point(451, 112);
            this.bnOutput.Name = "bnOutput";
            this.bnOutput.Size = new System.Drawing.Size(78, 25);
            this.bnOutput.TabIndex = 39;
            this.bnOutput.Text = "Chọn";
            this.bnOutput.UseVisualStyleBackColor = true;
            // 
            // bn_Input
            // 
            this.bn_Input.Location = new System.Drawing.Point(450, 54);
            this.bn_Input.Name = "bn_Input";
            this.bn_Input.Size = new System.Drawing.Size(78, 25);
            this.bn_Input.TabIndex = 40;
            this.bn_Input.Text = "Chọn";
            this.bn_Input.UseVisualStyleBackColor = true;
            this.bn_Input.Click += new System.EventHandler(this.bn_Input_Click);
            // 
            // textOutput
            // 
            this.textOutput.Location = new System.Drawing.Point(81, 116);
            this.textOutput.Name = "textOutput";
            this.textOutput.Size = new System.Drawing.Size(351, 20);
            this.textOutput.TabIndex = 37;
            // 
            // textInput
            // 
            this.textInput.Location = new System.Drawing.Point(81, 55);
            this.textInput.Name = "textInput";
            this.textInput.Size = new System.Drawing.Size(351, 20);
            this.textInput.TabIndex = 38;
            // 
            // lb_outputfile
            // 
            this.lb_outputfile.AutoSize = true;
            this.lb_outputfile.Location = new System.Drawing.Point(17, 118);
            this.lb_outputfile.Name = "lb_outputfile";
            this.lb_outputfile.Size = new System.Drawing.Size(43, 15);
            this.lb_outputfile.TabIndex = 35;
            this.lb_outputfile.Text = "Output";
            // 
            // lb_Inputdata
            // 
            this.lb_Inputdata.AutoSize = true;
            this.lb_Inputdata.Location = new System.Drawing.Point(17, 57);
            this.lb_Inputdata.Name = "lb_Inputdata";
            this.lb_Inputdata.Size = new System.Drawing.Size(34, 15);
            this.lb_Inputdata.TabIndex = 36;
            this.lb_Inputdata.Text = "Input";
            // 
            // Form1
            // 
            this.AutoScaleDimensions = new System.Drawing.SizeF(6F, 13F);
            this.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font;
            this.ClientSize = new System.Drawing.Size(546, 207);
            this.Controls.Add(this.cB_InputType);
            this.Controls.Add(this.lb_InputType);
            this.Controls.Add(this.bnCancel);
            this.Controls.Add(this.bn_option);
            this.Controls.Add(this.bnProcess);
            this.Controls.Add(this.bnOutput);
            this.Controls.Add(this.bn_Input);
            this.Controls.Add(this.textOutput);
            this.Controls.Add(this.textInput);
            this.Controls.Add(this.lb_outputfile);
            this.Controls.Add(this.lb_Inputdata);
            this.Name = "Form1";
            this.Text = "Form1";
            this.ResumeLayout(false);
            this.PerformLayout();

        }

        #endregion

        private System.Windows.Forms.ComboBox cB_InputType;
        private System.Windows.Forms.Label lb_InputType;
        private System.Windows.Forms.Button bnCancel;
        private System.Windows.Forms.Button bn_option;
        private System.Windows.Forms.Button bnProcess;
        private System.Windows.Forms.Button bnOutput;
        private System.Windows.Forms.Button bn_Input;
        private System.Windows.Forms.TextBox textOutput;
        private System.Windows.Forms.TextBox textInput;
        private System.Windows.Forms.Label lb_outputfile;
        private System.Windows.Forms.Label lb_Inputdata;
    }
}

