import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "金融 KOL 情报流 Dashboard",
  description: "金融交易 KOL 多平台情报流与标签化信号监控",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
