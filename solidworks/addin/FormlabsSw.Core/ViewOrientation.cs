using System;

namespace FormlabsSw.Core
{
    /// <summary>
    /// Maps the current SOLIDWORKS view to PreForm axes: "what you see is how it lands". SOLIDWORKS stores a view
    /// rotation as 9 doubles in the row-vector convention (view = model * M). The screen is X right, Y up, Z toward
    /// the viewer; PreForm is X right, Z up, front at -Y, so screen (a, b, c) becomes PreForm (a, -c, b).
    /// </summary>
    public static class ViewOrientation
    {
        /// <summary>Screen to PreForm, row-vector convention.</summary>
        public static readonly double[] ScreenToPreForm = { 1, 0, 0, 0, 0, 1, 0, -1, 0 };

        /// <summary>Row-major 3x3 product a * b (row-vector convention: apply a, then b).</summary>
        public static double[] Multiply(double[] a, double[] b)
        {
            var r = new double[9];
            for (int i = 0; i < 3; i++)
                for (int j = 0; j < 3; j++)
                    for (int k = 0; k < 3; k++) r[i * 3 + j] += a[i * 3 + k] * b[k * 3 + j];
            return r;
        }

        /// <summary>Model to PreForm for a view (the first nine numbers of IMathTransform.ArrayData).</summary>
        public static double[] FromView(double[] viewArrayData)
        {
            if (viewArrayData == null || viewArrayData.Length < 9) throw new ArgumentException("view transform needs 9 numbers");
            var view = new double[9];
            Array.Copy(viewArrayData, view, 9);
            return Multiply(view, ScreenToPreForm);
        }

        /// <summary>The same rotation as a column-vector 4x4 (what the service stores), millimetres, no translation.</summary>
        public static double[][] ToColumn4x4(double[] rowRot9)
        {
            var m = new double[4][];
            for (int i = 0; i < 4; i++) m[i] = new double[4];
            for (int i = 0; i < 3; i++)
                for (int j = 0; j < 3; j++) m[i][j] = rowRot9[j * 3 + i]; // transpose
            m[3][3] = 1;
            return m;
        }

        /// <summary>ArrayData for IMathUtility.CreateTransform: rotation, zero translation, scale 1.</summary>
        public static double[] ToSolidWorksArray(double[] rowRot9)
        {
            var a = new double[16];
            Array.Copy(rowRot9, a, 9);
            a[12] = 1;
            return a;
        }

        public static (double X, double Y, double Z) Apply(double[] rowRot9, double x, double y, double z) =>
            (x * rowRot9[0] + y * rowRot9[3] + z * rowRot9[6],
             x * rowRot9[1] + y * rowRot9[4] + z * rowRot9[7],
             x * rowRot9[2] + y * rowRot9[5] + z * rowRot9[8]);
    }
}
