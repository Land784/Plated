import { Suspense } from "react";

import { Frame, Header } from "@/components/plated/frame";
import { SignIn } from "@/components/plated/sign-in";

export default function SignInPage() {
  return (
    <Frame>
      <Header />
      <main className="mx-auto w-full flex-1 lg:max-w-md">
        <Suspense>
          <SignIn />
        </Suspense>
      </main>
    </Frame>
  );
}
