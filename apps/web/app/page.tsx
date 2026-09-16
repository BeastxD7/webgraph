import Backdrop from "@/components/landing/Backdrop";
import Closing from "@/components/landing/Closing";
import Motion from "@/components/landing/Motion";
import ProofStrip from "@/components/landing/ProofStrip";
import RefusesDrops from "@/components/landing/RefusesDrops";
import Standings from "@/components/landing/Standings";
import Story from "@/components/landing/Story";

/**
 * Five chapters. The first four share one sticky stage (`Story`): the promise, the pain,
 * the turn, the result. Then the proof — the numbers with their sources, what is refused
 * and dropped, the standings including where this engine loses — and the prompt to run it.
 * `Motion` adds the scroll reveals once JavaScript is up; the page is complete without it.
 */
export default function LandingPage() {
  return (
    <main className="landing relative isolate overflow-x-clip">
      <Backdrop />
      <Story />
      <ProofStrip />
      <RefusesDrops />
      <Standings />
      <Closing />
      <Motion />
    </main>
  );
}
