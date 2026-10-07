import { AppProvider } from "@/components/plated/app-provider";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return <AppProvider>{children}</AppProvider>;
}
