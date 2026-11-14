using System;

namespace FormlabsSw.Core
{
    /// <summary>
    /// Row-major 4x4 homogeneous transform, column vectors, right-handed, millimetres (spec §6.2).
    /// SOLIDWORKS stores lengths in metres: use <see cref="FromSolidWorksMetres"/> at the boundary.
    /// </summary>
    public sealed class Matrix4
    {
        public readonly double[,] M = new double[4, 4];

        public static Matrix4 Identity()
        {
            var r = new Matrix4();
            for (int i = 0; i < 4; i++) r.M[i, i] = 1;
            return r;
        }

        public static Matrix4 Translation(double x, double y, double z)
        {
            var r = Identity();
            r.M[0, 3] = x; r.M[1, 3] = y; r.M[2, 3] = z;
            return r;
        }

        public static Matrix4 Rotation(char axis, double degrees)
        {
            double c = Math.Cos(degrees * Math.PI / 180), s = Math.Sin(degrees * Math.PI / 180);
            var r = Identity();
            switch (axis)
            {
                case 'x': r.M[1, 1] = c; r.M[1, 2] = -s; r.M[2, 1] = s; r.M[2, 2] = c; break;
                case 'y': r.M[0, 0] = c; r.M[0, 2] = s; r.M[2, 0] = -s; r.M[2, 2] = c; break;
                case 'z': r.M[0, 0] = c; r.M[0, 1] = -s; r.M[1, 0] = s; r.M[1, 1] = c; break;
                default: throw new ArgumentException("axis must be x, y or z");
            }
            return r;
        }

        public static Matrix4 operator *(Matrix4 a, Matrix4 b)
        {
            var r = new Matrix4();
            for (int i = 0; i < 4; i++)
                for (int j = 0; j < 4; j++)
                    for (int k = 0; k < 4; k++) r.M[i, j] += a.M[i, k] * b.M[k, j];
            return r;
        }

        public (double X, double Y, double Z) Apply(double x, double y, double z)
        {
            double[] v = { x, y, z, 1 };
            var o = new double[3];
            for (int i = 0; i < 3; i++)
                for (int k = 0; k < 4; k++) o[i] += M[i, k] * v[k];
            return (o[0], o[1], o[2]);
        }

        /// <summary>Inverse of a rotation+translation matrix.</summary>
        public Matrix4 InvertRigid()
        {
            var r = Identity();
            for (int i = 0; i < 3; i++)
                for (int j = 0; j < 3; j++) r.M[i, j] = M[j, i];
            for (int i = 0; i < 3; i++)
                r.M[i, 3] = -(r.M[i, 0] * M[0, 3] + r.M[i, 1] * M[1, 3] + r.M[i, 2] * M[2, 3]);
            return r;
        }

        /// <summary>Rejects scale, shear, reflection and non-affine matrices.</summary>
        public void ValidateRigid(double tol = 1e-6)
        {
            for (int j = 0; j < 4; j++)
                if (Math.Abs(M[3, j] - (j == 3 ? 1 : 0)) > tol) throw new ArgumentException("last row must be [0,0,0,1]");
            for (int i = 0; i < 3; i++)
                for (int j = 0; j < 3; j++)
                {
                    double dot = 0;
                    for (int k = 0; k < 3; k++) dot += M[k, i] * M[k, j];
                    if (Math.Abs(dot - (i == j ? 1 : 0)) > tol) throw new ArgumentException("rotation block is not orthonormal");
                }
            double det = M[0, 0] * (M[1, 1] * M[2, 2] - M[1, 2] * M[2, 1])
                       - M[0, 1] * (M[1, 0] * M[2, 2] - M[1, 2] * M[2, 0])
                       + M[0, 2] * (M[1, 0] * M[2, 1] - M[1, 1] * M[2, 0]);
            if (det < 0) throw new ArgumentException("transform is left-handed");
        }

        /// <summary>
        /// Builds from an IMathTransform.ArrayData (SOLIDWORKS 16 doubles: 3x3 rotation row-major,
        /// translation (metres), scale, padding) into a millimetre matrix.
        /// </summary>
        public static Matrix4 FromSolidWorksMetres(double[] a)
        {
            if (a == null || a.Length < 13) throw new ArgumentException("expected 16 doubles from IMathTransform.ArrayData");
            var r = Identity();
            for (int i = 0; i < 3; i++)
                for (int j = 0; j < 3; j++) r.M[i, j] = a[i * 3 + j];
            r.M[0, 3] = a[9] * 1000; r.M[1, 3] = a[10] * 1000; r.M[2, 3] = a[11] * 1000;
            return r;
        }

        public double[][] ToJagged()
        {
            var o = new double[4][];
            for (int i = 0; i < 4; i++) { o[i] = new double[4]; for (int j = 0; j < 4; j++) o[i][j] = M[i, j]; }
            return o;
        }
    }
}
