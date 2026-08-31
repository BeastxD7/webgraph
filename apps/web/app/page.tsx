import Capabilities from "@/components/landing/Capabilities";
import Evidence from "@/components/landing/Evidence";
import Hero from "@/components/landing/Hero";
import Pipeline from "@/components/landing/Pipeline";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import HeroBackdrop from "@/components/ui/HeroBackdrop";

export default function LandingPage() {
  return (
    <>
      <section className="relative isolate overflow-hidden">
        <HeroBackdrop priority />
        <SiteHeader />
        <Hero />
      </section>

      <main>
        <Capabilities />
        <Pipeline />
        <Evidence />
      </main>

      <SiteFooter />
    </>
  );
}
