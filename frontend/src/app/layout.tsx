import type { Metadata } from "next";
import "leaflet/dist/leaflet.css";
import "./globals.css";
import Shell from "@/components/Shell";

export const metadata: Metadata = {
  title: "RAHAT · Predictive Forward Supply Chain",
  description:
    "RAHAT — AI demand forecasting, GIS corridor planning, IoT stock tracking and a counterfactual mission-simulation digital twin for forward logistics. Smart India Hackathon 2026, problem statement SIH26251.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      data-scroll-behavior="smooth"
      className="h-full antialiased"
    >
      <body className="min-h-full">
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
