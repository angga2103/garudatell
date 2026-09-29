$csharp = @"
using System;
using System.IO;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Text;

public class IPayIconGenerator
{
    private static GraphicsPath CreateRoundedRectangle(RectangleF rect, float radius)
    {
        GraphicsPath path = new GraphicsPath();
        float diameter = radius * 2;
        RectangleF arc = new RectangleF(rect.X, rect.Y, diameter, diameter);

        path.AddArc(arc, 180, 90);
        arc.X = rect.Right - diameter;
        path.AddArc(arc, 270, 90);
        arc.Y = rect.Bottom - diameter;
        path.AddArc(arc, 0, 90);
        arc.X = rect.Left;
        path.AddArc(arc, 90, 90);
        path.CloseFigure();
        return path;
    }

    public static void GenerateIcon(int size, string outputPath, bool isMaskable)
    {
        using (Bitmap bmp = new Bitmap(size, size, PixelFormat.Format32bppArgb))
        using (Graphics g = Graphics.FromImage(bmp))
        {
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.PixelOffsetMode = PixelOffsetMode.HighQuality;

            RectangleF rect = new RectangleF(0, 0, size, size);

            // 1. Background Gradient (Fintech Teal - Emerald)
            Color colorTop = Color.FromArgb(0, 75, 68);      // Deep Teal #004b44
            Color colorBottom = Color.FromArgb(0, 160, 140); // Bright Emerald #00a08c

            using (LinearGradientBrush bgBrush = new LinearGradientBrush(
                new PointF(0, 0),
                new PointF(size, size),
                colorTop,
                colorBottom))
            {
                if (isMaskable)
                {
                    g.FillRectangle(bgBrush, rect);
                }
                else
                {
                    float radius = size * 0.22f;
                    using (GraphicsPath path = CreateRoundedRectangle(rect, radius))
                    {
                        g.FillPath(bgBrush, path);
                        using (Pen borderPen = new Pen(Color.FromArgb(50, 255, 255, 255), Math.Max(1.5f, size * 0.015f)))
                        {
                            g.DrawPath(borderPen, path);
                        }
                    }
                }
            }

            // 2. Decorative Geometry (Subtle glowing rings)
            using (Pen ringPen = new Pen(Color.FromArgb(20, 255, 255, 255), size * 0.035f))
            {
                g.DrawEllipse(ringPen, size * 0.15f, size * 0.10f, size * 0.95f, size * 0.95f);
            }

            // 3. Dynamic Scales
            float safeScale = isMaskable ? 0.78f : 0.92f;
            float fontSize = size * 0.32f * safeScale;

            using (Font mainFont = new Font("Segoe UI", fontSize, FontStyle.Bold, GraphicsUnit.Pixel))
            {
                // Calculate size of "i" and "Pay"
                SizeF sizeI = g.MeasureString("i", mainFont);
                SizeF sizePay = g.MeasureString("Pay", mainFont);

                float spacingAdjust = size * 0.01f;
                float effectiveWidthI = sizeI.Width * 0.60f;
                float effectiveWidthPay = sizePay.Width * 0.90f;
                float totalWidth = effectiveWidthI + effectiveWidthPay - spacingAdjust;

                float startX = (size - totalWidth) / 2f;
                float startY = (size - sizePay.Height) / 2f - (size >= 128 ? size * 0.04f : 0);

                // Drop Shadow for 3D depth
                using (SolidBrush shadowBrush = new SolidBrush(Color.FromArgb(90, 0, 30, 25)))
                {
                    g.DrawString("i", mainFont, shadowBrush, startX + size * 0.012f, startY + size * 0.018f);
                    g.DrawString("Pay", mainFont, shadowBrush, startX + effectiveWidthI - spacingAdjust + size * 0.012f, startY + size * 0.018f);
                }

                // Crisp White Text
                using (SolidBrush whiteBrush = new SolidBrush(Color.FromArgb(255, 255, 255)))
                {
                    g.DrawString("i", mainFont, whiteBrush, startX, startY);
                    g.DrawString("Pay", mainFont, whiteBrush, startX + effectiveWidthI - spacingAdjust, startY);
                }

                // Golden Glow Dot on "i"
                float dotDiameter = size * 0.082f * safeScale;
                float dotX = startX + (effectiveWidthI - dotDiameter) / 2f + size * 0.012f;
                float dotY = startY + size * 0.042f * safeScale;

                using (LinearGradientBrush goldBrush = new LinearGradientBrush(
                    new RectangleF(dotX, dotY, dotDiameter, dotDiameter),
                    Color.FromArgb(255, 235, 59),  // Bright Yellow
                    Color.FromArgb(245, 158, 11),  // Amber Gold
                    LinearGradientMode.ForwardDiagonal))
                {
                    g.FillEllipse(goldBrush, dotX, dotY, dotDiameter, dotDiameter);
                }
            }

            // 4. Subtitle "GARUDATEL" for larger icons
            if (size >= 128)
            {
                float subFontSize = size * 0.062f * safeScale;
                using (Font subFont = new Font("Segoe UI", subFontSize, FontStyle.Bold, GraphicsUnit.Pixel))
                using (SolidBrush subBrush = new SolidBrush(Color.FromArgb(210, 230, 245, 240)))
                {
                    string subText = "GARUDATEL";
                    SizeF subSize = g.MeasureString(subText, subFont);
                    float subX = (size - subSize.Width) / 2f;
                    float subY = size * 0.68f;
                    g.DrawString(subText, subFont, subBrush, subX, subY);
                }
            }

            // Ensure directory exists
            string dir = Path.GetDirectoryName(outputPath);
            if (!Directory.Exists(dir))
            {
                Directory.CreateDirectory(dir);
            }

            bmp.Save(outputPath, ImageFormat.Png);
            Console.WriteLine("Generated: " + outputPath + " (" + size + "x" + size + ")");
        }
    }
}
"@

Add-Type -TypeDefinition $csharp -ReferencedAssemblies "System.Drawing"

$outDir = "C:\garudatelv2\garudatel\app\static\img\icons"

[IPayIconGenerator]::GenerateIcon(192, "$outDir\icon-192x192.png", $false)
[IPayIconGenerator]::GenerateIcon(512, "$outDir\icon-512x512.png", $false)
[IPayIconGenerator]::GenerateIcon(192, "$outDir\icon-maskable-192x192.png", $true)
[IPayIconGenerator]::GenerateIcon(512, "$outDir\icon-maskable-512x512.png", $true)
[IPayIconGenerator]::GenerateIcon(180, "$outDir\apple-touch-icon.png", $false)
[IPayIconGenerator]::GenerateIcon(32,  "$outDir\favicon-32x32.png", $false)
[IPayIconGenerator]::GenerateIcon(16,  "$outDir\favicon-16x16.png", $false)

Write-Output "ALL ICONS GENERATED PERFECTLY!"
