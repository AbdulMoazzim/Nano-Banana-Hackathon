import type { Metadata } from "next";
import { Geist, Geist_Mono, Inter } from "next/font/google";
import "./globals.css";
import { cn } from "@/lib/utils";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "SortWise AI | Waste identification and sorting guidance",
    template: "%s | SortWise AI",
  },
  description:
    "Upload a photo of a waste item to identify it, check its visible condition, and get general disposal guidance.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
    data-scroll-behavior="smooth"
      lang="en"
      className={cn(
        "h-full scroll-smooth",
        "antialiased",
        geistSans.variable,
        geistMono.variable,
        "font-sans",
        inter.variable
      )}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}