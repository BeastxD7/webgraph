import Hero from "@/components/landing/Hero";
import Pipeline from "@/components/landing/Pipeline";
import ProofStrip from "@/components/landing/ProofStrip";
import RefusesDrops from "@/components/landing/RefusesDrops";
import Standings from "@/components/landing/Standings";

export default function LandingPage() {
  return (
    <main>
      <Hero />
      <ProofStrip />
      <RefusesDrops />
      <Pipeline />
      <Standings />
    </main>
  );
}
