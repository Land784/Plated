import { Suspense } from "react";

import { Frame, Header } from "@/components/plated/frame";
import { SignIn } from "@/components/plated/sign-in";

export default function SignInPage() {
  return (
    <Frame>
      <Header />
      <main className="flex-1">
        <Suspense>
          <SignIn />
        </Suspense>
      </main>
    </Frame>
  );
}
