import Link from "next/link";
import { Brand, GitHubLink } from "@/components/brand";
import { ProductIcon } from "@/components/product-icons";
import { OutboundDemoDialog, OutboundDemoTrigger } from "@/features/outbound-demo/outbound-demo-dialog";
export const dynamic = "force-dynamic";

export default function Home() {
  return <OutboundDemoDialog><div className="public-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header className="top-nav"><Brand/><nav aria-label="Main navigation"><GitHubLink/><a href="#workflow">How it works</a><Link href="/calls" className="secondary">Call workspace →</Link></nav></header>
    <main id="main-content">
      <section className="hero conversation-hero">
        <div><p className="eyebrow">OUTBOUND AI VOICE AGENT</p><h1>One requested call.<br/>A natural conversation.<br/><em>A clear next step.</em></h1>
          <p className="hero-summary">DwellCall is a focused real-estate callback agent. It asks useful questions, listens to corrections and turns a property conversation into a transcript and qualification summary.</p>
          <div className="hero-actions"><OutboundDemoTrigger>Request a demo call</OutboundDemoTrigger><Link href="/calls">Open the call workspace →</Link></div>
          <p className="muted fine-print">A requested AI demonstration · up to three minutes · fictional property scenarios.</p>
        </div>
        <aside className="call-showcase" aria-label="Example outbound call workflow">
          <div className="call-showcase-heading"><ProductIcon name="phone"/><span>THE CALL WORKFLOW</span></div>
          <h2>Listen first.<br/>Ask what matters.</h2><p>A useful conversation about renting, buying or finding something exceptional.</p>
          <ol><li><strong>Request</strong><span>Choose a scenario and confirm permission.</span></li><li><strong>Conversation</strong><span>Discuss property needs, timing and next steps.</span></li><li><strong>Result</strong><span>Review the transcript, stated needs and follow-up permission.</span></li></ol>
          <p className="fine-print">Illustrated workflow. Live calling and transcript analysis require owner configuration and acceptance.</p>
        </aside>
      </section>
      <section id="workflow" className="workflow-section"><div className="section-heading"><p className="eyebrow">FROM REQUEST TO RESULT</p><h2>A small workflow.<br/>Useful from end to end.</h2></div>
        <div className="workflow-grid">{[
          ["01", "Start deliberately", "An approved operator requests one call to a consenting recipient. The homepage demo verifies the recipient’s number before calling."],
          ["02", "Have the conversation", "The AI identifies itself, asks permission, follows the scenario and handles corrections. The person can finish at any time."],
          ["03", "Review what was said", "With transcript analysis enabled, the workspace retains the conversation securely and shows a summary supported by recipient quotes."],
        ].map(([number, title, description]) => <article key={number}><span className="eyebrow">{number}</span><h3>{title}</h3><p>{description}</p></article>)}</div>
        <div className="notice">Demonstration conversations use fictional details. This showcase does not book appointments or arrange further contact. Live behavior remains unverified pending owner acceptance.</div>
      </section>
    </main>
    <footer className="public-footer"><Brand/><span>Requested calls. Clear outcomes.</span><Link href="/calls">Call workspace →</Link></footer>
  </div></OutboundDemoDialog>;
}
