/* eslint-disable @next/next/no-html-link-for-pages -- these are deliberately raw <a>
   hard navigations: the root layout (and its body.legacy class) persists across client
   <Link> navigations, so leaving the skin requires a full document load. */
// Period-correct chrome for the Windows-98 "legacy" skin: a scrolling title-bar
// marquee at the very top and a hit-counter status bar at the very bottom. Rendered
// from the root layout only when legacy mode is active. Pure markup — the look lives
// in app/legacy.css (.legacy-* classes). The marquee scrolls via CSS (the <marquee>
// tag is long deprecated), with the text duplicated so the loop is seamless.

const MARQUEE =
  "★★★ WELCOME TO QFINZERO CONSOLE · Quant Factor Research since 2003 · " +
  "Best viewed in 1024×768 with Netscape Navigator · ";

export function LegacyBanner() {
  return (
    <div className="legacy-banner">
      <div className="legacy-marquee">
        <div className="legacy-marquee__track">
          <span>
            {MARQUEE}
            <span className="legacy-blink">NEW!</span> now with live PMB tracking! · sign our
            guestbook! &#9733;&#9733;&#9733;&nbsp;&nbsp;&nbsp;
          </span>
          <span aria-hidden="true">
            {MARQUEE}
            <span className="legacy-blink">NEW!</span> now with live PMB tracking! · sign our
            guestbook! &#9733;&#9733;&#9733;&nbsp;&nbsp;&nbsp;
          </span>
        </div>
      </div>
    </div>
  );
}

// Stay under the /legacy prefix so the retro skin sticks as you browse.
const SECTION_LINKS = [
  { href: "/legacy", label: "Chat" },
  { href: "/legacy/data", label: "Data" },
  { href: "/legacy/pmb", label: "PMB" },
  { href: "/legacy/settings", label: "Settings" },
  { href: "/legacy/doc", label: "Doc" },
];

export function LegacyFooter() {
  return (
    <div className="legacy-foot">
      <hr />
      You are visitor <span className="legacy-counter">00013370</span> &nbsp;|&nbsp;
      <span className="legacy-blink"> &#9679; </span> Made with Notepad &nbsp;|&nbsp; &copy; 2003
      QFinZero Labs &nbsp;|&nbsp; <a href="/">&laquo; back to the modern site</a>
      <div style={{ marginTop: 6 }}>
        [&nbsp;
        {SECTION_LINKS.map((l, i) => (
          <span key={l.href}>
            {i > 0 && " | "}
            <a href={l.href}>{l.label}</a>
          </span>
        ))}
        &nbsp;] &middot; <span className="legacy-uc">This site is under construction</span> &#128679;
      </div>
    </div>
  );
}
