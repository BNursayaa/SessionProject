import "./globals.css";

export const metadata = {
  title: "Digital Twin — Motor",
  description: "Monitoring + Predictive Maintenance (prototype)"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}

