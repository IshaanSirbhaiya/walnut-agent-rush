import type { Metadata } from 'next';
import { PresenterRoot } from '@/components/presenter/PresenterRoot';

export const metadata: Metadata = { title: 'Walnut DataBridge · Presenter' };

// Full-bleed slides for the presenter script (no app shell, no session needed). The presenter bar
// is mounted here so Space keeps driving the script on the slides.
export default function PresentLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <main id="main" tabIndex={-1} className="focus:outline-none">
        {children}
      </main>
      <PresenterRoot />
    </>
  );
}
