import { AppProvider } from "@/components/plated/app-provider";

import PreviewPage from "./preview/page";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return <AppProvider aside={<PreviewPage />}>{children}</AppProvider>;
}
