using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
//using CSML;
namespace WF_GNSS_Adj
{
    
    
    public class pmatrix
    {
        public static double[][] MatrixCreate(int rows, int cols)
        {
            double[][] result = new double[rows][];
            for (int i = 0; i < rows; ++i)
                result[i] = new double[cols];
            return result;
        }

        public static double[][] Transpose(double[][] matrix)
        {  
            int w = matrix.Count();
            int h = matrix[0].Count();

            double[][] result = pmatrix.MatrixCreate(h, w);

            for (int i = 0; i < w; i++)
            {
                for (int j = 0; j < h; j++)
                {
                    result[j][i] = matrix[i][j];
                }
            }

            return result;
        }

        // --------------------------------------------------

        public static double[][] MatrixRandom(int rows, int cols,
             double minVal, double maxVal, int seed)
        {
            // return a matrix with random values
            Random ran = new Random(seed);
            double[][] result = MatrixCreate(rows, cols);
            for (int i = 0; i < rows; ++i)
                for (int j = 0; j < cols; ++j)
                    result[i][j] = (maxVal - minVal) *
                      ran.NextDouble() + minVal;
            return result;
        }

        // --------------------------------------------------

        public static double[][] MatrixIdentity(int n)
        {
            // return an n x n Identity matrix
            double[][] result = MatrixCreate(n, n);
            for (int i = 0; i < n; ++i)
                result[i][i] = 1.0;

            return result;
        }

        // --------------------------------------------------

        public static string MatrixAsString(double[][] matrix, int dec)
        {
            string s = "";
            for (int i = 0; i < matrix.Length; ++i)
            {
                for (int j = 0; j < matrix[i].Length; ++j)
                    s += matrix[i][j].ToString("F" + dec).PadLeft(8) + " ";
                s += Environment.NewLine;
            }
            return s;
        }

        // --------------------------------------------------

        public static bool MatrixAreEqual(double[][] matrixA,
             double[][] matrixB, double epsilon)
        {
            // true if all values in matrixA == values in matrixB
            int aRows = matrixA.Length; int aCols = matrixA[0].Length;
            int bRows = matrixB.Length; int bCols = matrixB[0].Length;
            if (aRows != bRows || aCols != bCols)
                throw new Exception("Non-conformable matrices");

            for (int i = 0; i < aRows; ++i) // each row of A and B
                for (int j = 0; j < aCols; ++j) // each col of A and B
                    //if (matrixA[i][j] != matrixB[i][j])
                    if (Math.Abs(matrixA[i][j] - matrixB[i][j]) > epsilon)
                        return false;
            return true;
        }

        // --------------------------------------------------

        public static double[][] MatrixProduct(double[][] matrixA, double[][] matrixB)
        {
            int aRows = matrixA.Length; int aCols = matrixA[0].Length;
            int bRows = matrixB.Length; int bCols = matrixB[0].Length;
            if (aCols != bRows)
                throw new Exception("Non-conformable matrices in MatrixProduct");

            double[][] result = MatrixCreate(aRows, bCols);

            for (int i = 0; i < aRows; ++i) // each row of A
                for (int j = 0; j < bCols; ++j) // each col of B
                    for (int k = 0; k < aCols; ++k) // could use k < bRows
                        result[i][j] += matrixA[i][k] * matrixB[k][j];

             return result;
        }

        // --------------------------------------------------

        public static double[] MatrixVectorProduct(double[][] matrix,
           double[] vector)
        {
   
            int mRows = matrix.Length; int mCols = matrix[0].Length;
            int vRows = vector.Length;
            if (mCols != vRows)
                throw new Exception("Non-conformable matrix and vector");
            double[] result = new double[mRows];
            for (int i = 0; i < mRows; ++i)
                for (int j = 0; j < mCols; ++j)
                    result[i] += matrix[i][j] * vector[j];
            return result;
        }

        // --------------------------------------------------

        public static double[][] MatrixDecompose(double[][] matrix, out int[] perm,
           out int toggle)
        {
            // Doolittle LUP decomposition with partial pivoting.
            // rerturns: result is L (with 1s on diagonal) and U;
            // perm holds row permutations; toggle is +1 or -1 (even or odd)
            int rows = matrix.Length;
            int cols = matrix[0].Length; // assume square
            if (rows != cols)
                throw new Exception("Attempt to decompose a non-square m");

            int n = rows; // convenience

            double[][] result = MatrixDuplicate(matrix);

            perm = new int[n]; // set up row permutation result
            for (int i = 0; i < n; ++i) { perm[i] = i; }

            toggle = 1; // toggle tracks row swaps.
            // +1 -> even, -1 -> odd. used by MatrixDeterminant

            for (int j = 0; j < n - 1; ++j) // each column
            {
                double colMax = Math.Abs(result[j][j]); // find largest val in col
                int pRow = j;
                //for (int i = j + 1; i < n; ++i)
                //{
                //  if (result[i][j] > colMax)
                //  {
                //    colMax = result[i][j];
                //    pRow = i;
                //  }
                //}

                // reader Matt V needed this:
                for (int i = j + 1; i < n; ++i)
                {
                    if (Math.Abs(result[i][j]) > colMax)
                    {
                        colMax = Math.Abs(result[i][j]);
                        pRow = i;
                    }
                }
                // Not sure if this approach is needed always, or not.

                if (pRow != j) // if largest value not on pivot, swap rows
                {
                    double[] rowPtr = result[pRow];
                    result[pRow] = result[j];
                    result[j] = rowPtr;

                    int tmp = perm[pRow]; // and swap perm info
                    perm[pRow] = perm[j];
                    perm[j] = tmp;

                    toggle = -toggle; // adjust the row-swap toggle
                }

                // --------------------------------------------------
                // This part added later (not in original)
                // and replaces the 'return null' below.
                // if there is a 0 on the diagonal, find a good row
                // from i = j+1 down that doesn't have
                // a 0 in column j, and swap that good row with row j
                // --------------------------------------------------

                if (result[j][j] == 0.0)
                {
                    // find a good row to swap
                    int goodRow = -1;
                    for (int row = j + 1; row < n; ++row)
                    {
                        if (result[row][j] != 0.0)
                            goodRow = row;
                    }

                    if (goodRow == -1)
                        throw new Exception("Cannot use Doolittle's method");

                    // swap rows so 0.0 no longer on diagonal
                    double[] rowPtr = result[goodRow];
                    result[goodRow] = result[j];
                    result[j] = rowPtr;

                    int tmp = perm[goodRow]; // and swap perm info
                    perm[goodRow] = perm[j];
                    perm[j] = tmp;

                    toggle = -toggle; // adjust the row-swap toggle
                }
                // --------------------------------------------------
                // if diagonal after swap is zero . .
                //if (Math.Abs(result[j][j]) < 1.0E-20) 
                //  return null; // consider a throw

                for (int i = j + 1; i < n; ++i)
                {
                    result[i][j] /= result[j][j];
                    for (int k = j + 1; k < n; ++k)
                    {
                        result[i][k] -= result[i][j] * result[j][k];
                    }
                }


            } // main j column loop

            return result;
        } // MatrixDecompose

        // --------------------------------------------------

        public static double[][] MatrixInverse(double[][] matrix)
        {
            int n = matrix.Length;
            double[][] result = MatrixDuplicate(matrix);

            int[] perm;
            int toggle;
            double[][] lum = MatrixDecompose(matrix, out perm,
              out toggle);
            if (lum == null)
                throw new Exception("Unable to compute inverse");

            double[] b = new double[n];
            for (int i = 0; i < n; ++i)
            {
                for (int j = 0; j < n; ++j)
                {
                    if (i == perm[j])
                        b[j] = 1.0;
                    else
                        b[j] = 0.0;
                }

                double[] x = HelperSolve(lum, b); // 

                for (int j = 0; j < n; ++j)
                    result[j][i] = x[j];
            }
            return result;
        }

        // --------------------------------------------------

        public static double MatrixDeterminant(double[][] matrix)
        {
            int[] perm;
            int toggle;
            double[][] lum = MatrixDecompose(matrix, out perm, out toggle);
            if (lum == null)
                throw new Exception("Unable to compute MatrixDeterminant");
            double result = toggle;
            for (int i = 0; i < lum.Length; ++i)
                result *= lum[i][i];
            return result;
        }

        // --------------------------------------------------

        public static double[] HelperSolve(double[][] luMatrix, double[] b)
        {
            // before calling this helper, permute b using the perm array
            // from MatrixDecompose that generated luMatrix
            int n = luMatrix.Length;
            double[] x = new double[n];
            b.CopyTo(x, 0);

            for (int i = 1; i < n; ++i)
            {
                double sum = x[i];
                for (int j = 0; j < i; ++j)
                    sum -= luMatrix[i][j] * x[j];
                x[i] = sum;
            }

            x[n - 1] /= luMatrix[n - 1][n - 1];
            for (int i = n - 2; i >= 0; --i)
            {
                double sum = x[i];
                for (int j = i + 1; j < n; ++j)
                    sum -= luMatrix[i][j] * x[j];
                x[i] = sum / luMatrix[i][i];
            }

            return x;
        }

        // --------------------------------------------------

        public static double[] SystemSolve(double[][] A, double[] b)
        {
            // Solve Ax = b
            int n = A.Length;

            // 1. decompose A
            int[] perm;
            int toggle;
            double[][] luMatrix = MatrixDecompose(A, out perm,
              out toggle);
            if (luMatrix == null)
                return null;

            // 2. permute b according to perm[] into bp
            double[] bp = new double[b.Length];
            for (int i = 0; i < n; ++i)
                bp[i] = b[perm[i]];

            // 3. call helper
            double[] x = HelperSolve(luMatrix, bp);
            return x;
        } // SystemSolve

        // --------------------------------------------------

        public static double[][] MatrixDuplicate(double[][] matrix)
        {
            // allocates/creates a duplicate of a matrix.
            double[][] result = MatrixCreate(matrix.Length, matrix[0].Length);
            for (int i = 0; i < matrix.Length; ++i) // copy the values
                for (int j = 0; j < matrix[i].Length; ++j)
                    result[i][j] = matrix[i][j];
            return result;
        }

        public static double[][] AddMatrix(double[][] A, double[][] B)
        {
            double[][] result = MatrixCreate(A.Length, A[0].Length);
            for (int i = 0; i < A.Length; ++i) // copy the values
                for (int j = 0; j < A[i].Length; ++j)
                    result[i][j] = A[i][j] + B[i][j];
            return result;

        }
        public static double[][] SubMatrix(double[][] A, double[][] B)
        {
            double[][] result = MatrixCreate(A.Length, A[0].Length);
            for (int i = 0; i < A.Length; ++i) // copy the values
                for (int j = 0; j < A[i].Length; ++j)
                    result[i][j] = A[i][j] - B[i][j];
            return result;

        }

        // --------------------------------------------------
    }

    public class Trans_para
    {
        //double X0, Y0, m, alfa;//2Dtransform paras
        //double X0R, Y0R, mR, alfaR;//2Dtransform paras
        //double dx, dy, dz, rx, ry, rz, sc;//3D transform paras
        /// <summary>
        /// Hàm xác định các tham số chuyển đổi 2D
        /// đầu vào các điểm song trùng trong hệ tọa độ phẳng NEH
        /// listPO các điểm trong hệ gốc(hệ VN-2000)
        /// listPT các điểm trong hệ cần chuyển đến(Hệ tọa độ công trình)
        /// Đầu ra là các tham số chuyển đổi bao gồm X0, Y0, Z0,alfa va m;
        /// </summary>
        /// <param name="listPO"></param>
        /// <param name="listPT"></param>
        /// <returns></returns>
        public static double[] get2Dtransform(List<Point3D> listPO, List<Point3D> listPT)
        {
            double[] tran_paras = new double[5];
            if (listPO.Count == 0 || listPT.Count == 0)
            {
                throw new Exception("Need at leat 1 pair of points for transformation");
                //return null;
            }
            if (listPO.Count < 2 && listPT.Count < 2)
            {
                tran_paras[0] = listPT[0].X - listPO[0].X;
                tran_paras[1] = listPT[0].Y - listPO[0].Y;
                tran_paras[2] = listPT[0].Z - listPO[0].Z;
                tran_paras[3] = 0.0;
                tran_paras[4] = 1.0;

                return tran_paras;


            }
            else
            {
                double[][] matrixA = pmatrix.MatrixCreate(listPO.Count * 2, 4);
                double[] matrixL = new double[listPO.Count * 2];
                for (int i = 0; i < listPO.Count; i++)
                {
                    matrixA[i * 2][0] = 1.0; matrixA[i * 2][1] = 0.0; matrixA[i * 2][2] = listPO[i].X; matrixA[i * 2][3] = -listPO[i].Y;
                    matrixA[i * 2 + 1][0] = 0.0; matrixA[i * 2 + 1][1] = 1.0; matrixA[i * 2 + 1][2] = listPO[i].Y; matrixA[i * 2 + 1][3] = listPO[i].X;
                    matrixL[i * 2] = -listPT[i].X;
                    matrixL[i * 2 + 1] = -listPT[i].Y;
                }
                double[][] At = pmatrix.Transpose(matrixA);
                double[][] R = pmatrix.MatrixProduct(At, matrixA);
                double[] b = pmatrix.MatrixVectorProduct(At, matrixL);

                double[][] Q = pmatrix.MatrixInverse(R);
                double[] X = pmatrix.MatrixVectorProduct(Q, b);
                for (int i = 0; i < X.Count(); i++) X[i] = -X[i];


                tran_paras[0] = X[0];//X0
                tran_paras[1] = X[1];//Y0
                tran_paras[2] = listPT[0].Z - listPO[0].Z;
                tran_paras[3] = Math.Atan(X[3] / X[2]);//alfa
                tran_paras[4] = X[2] / Math.Cos(tran_paras[3]);//m

                return tran_paras;

            }


        }
        public static Point3D TransFrom(Point3D PO, double[] tranpara)
        {
            Point3D PT = new Point3D();
            PT.X = tranpara[0] + PO.X * tranpara[4] * Math.Cos(tranpara[3]) - PO.Y * tranpara[4] * Math.Sin(tranpara[3]);
            PT.Y = tranpara[1] + PO.X * tranpara[4] * Math.Sin(tranpara[3]) + PO.Y * tranpara[4] * Math.Cos(tranpara[3]);
            PT.Z = PO.Z + tranpara[2];
            return PT;
        }
        Point3D PT = new Point3D();
    
        public static Point3D HMTransFrom3D(Point3D PO, double[] tranpara)
        {
            Point3D PT = new Point3D();
            double dx=tranpara[0];
            double dy=tranpara[1];
            double dz=tranpara[2];
            double r1=tranpara[3];
            double r2=tranpara[4];
            double r3=tranpara[5];
            double M =tranpara[6];
            double rx=r1*(Math.PI/(3600.0*180.0));
            double ry=r2*(Math.PI/(3600.0*180.0));
            double rz=r3*(Math.PI/(3600.0*180.0));
            double[][] R = pmatrix.MatrixCreate(3, 3);
            R[0][0]=1.0*M; R[0][1]=rz*M; R[0][2]=-ry*M;
            R[1][0]=-rz*M; R[1][1]=1.0*M; R[1][2]=rx*M;
            R[2][0]=ry*M; R[2][1]=-rx*M; R[2][2]=1*M;
             double[] X = new double[3];
            X[0]=PO.X;
            X[1]=PO.Y;
            X[2]=PO.Z;
             double[] RX = pmatrix.MatrixVectorProduct(R, X);
            PT.X= RX[0]+dx;
            PT.Y= RX[1]+dy;
            PT.Z= RX[2]+dz;
            return PT;
        }

        public static void Test_TransFrom()
        {
            //Khởi tạo 2 điểm trong hệ tọa độ gốc (vd vn2000) và add vào danh sách
            List<Point3D> listPO = new List<Point3D>();
            Point3D PO1 = new Point3D();
            Point3D PO2 = new Point3D();
            PO1.X = 2.307; PO1.Y = 3.012; PO1.Z = 10.1; listPO.Add(PO1);
            PO2.X = 3.258; PO2.Y = 4.223; PO2.Z = 12.2; listPO.Add(PO2);

            //Khởi tạo 2 điểm trong hệ tọa độ cần chuyển đến(td công trình) và add vào danh sách
            List<Point3D> listPT = new List<Point3D>();
            Point3D PT1 = new Point3D();
            Point3D PT2 = new Point3D();
            PT1.X = 38.319; PT1.Y = 19.548; PT1.Z = 1.1; listPT.Add(PT1);
            PT2.X = 39.509; PT2.Y = 20.525; PT2.Z = 2.20; listPT.Add(PT2);

            //Khởi tại tham số thuận và đảo
            double[] tranpara = new double[5];
            double[] tranparaR = new double[5];
            tranpara = Trans_para.get2Dtransform(listPO, listPT);//Xác định tham số thuận
            tranparaR = Trans_para.get2Dtransform(listPT, listPO);// Xác định tham số đảo

            //Tạo một điểm để thử nghiệm.
            Point3D PO4 = new Point3D();
            PO4.X = 4.402; PO4.Y = 1.927; PO4.Z = 5.5; ;
            Point3D PT4 = new Point3D();
            PT4 = Trans_para.TransFrom(PO4, tranpara); //Tính thử tham số xuôi
            PO4 = Trans_para.TransFrom(PT4, tranparaR);// Tính thử tham số ngược
        }


    }

    
    

}


