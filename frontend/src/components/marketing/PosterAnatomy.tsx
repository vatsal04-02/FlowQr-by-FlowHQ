import { Pin, Poster } from "./Poster";

// Position of each marker on the artwork, as % of the poster (left, top).
const PINS: [number, number][] = [[7, 12], [4, 33], [21, 29], [7, 66], [13, 83]];

const PARTS: [string, string][] = [
  ["Review us on Google", "The header says what the card is for, with the five-star cue, before anyone has to read anything else."],
  ["Tap to Review", "Hold a phone to the card and the review page opens. NFC cards are programmed with the card's own link."],
  ["Scan to Review", "The QR opens the same page. Every card has its own permanent link, so you can change your Google review link without reprinting."],
  ["AI Review Assistant", "Customers can have their own words tidied up before they post. They edit the suggestion and submit the review themselves."],
  ["Write a Review", "The call to action. On paper it is artwork, so the action is the tap or the scan."],
];

/** The poster, annotated: what each part of the printed card does. Orange block matches the artwork. */
export function PosterAnatomy() {
  return (
    <section id="product" className="bg-flow-500 py-14 text-ink sm:py-20">
      <div className="container-page grid items-center gap-10 lg:grid-cols-[minmax(0,.9fr)_minmax(0,1.1fr)] lg:gap-16">
        <figure className="relative mx-auto w-full max-w-[400px] lg:order-2 lg:max-w-[430px]">
          <div style={{ filter: "drop-shadow(0 30px 34px rgba(23,23,25,.34))" }}><Poster /></div>
          {PINS.map(([x, y], i) => <div key={i} className="absolute" style={{ left: `${x}%`, top: `${y}%` }}><Pin n={i + 1} className="-translate-x-1/2 -translate-y-1/2" /></div>)}
          <figcaption className="mt-5 text-xs text-ink/80">Illustrative example. The QR on the artwork is a sample; each real card has its own generated code.</figcaption>
        </figure>
        <div className="lg:order-1">
          <p className="text-xs font-medium uppercase tracking-[.12em] text-ink/75">The FlowQR card</p>
          <h2 className="mt-2 max-w-xl text-3xl font-bold leading-[1.1] tracking-[-.03em] sm:text-[2.5rem]">One poster. Two ways in. One permanent link.</h2>
          <p className="mt-4 max-w-lg text-[17px] leading-relaxed text-ink/90">The card asks for one thing: a review. Everything printed on it either explains that or makes it a tap away.</p>
          <ol className="mt-7 divide-y divide-ink/20 border-y border-ink/20">
            {PARTS.map(([t, b], i) => (
              <li key={t} className="grid grid-cols-[1.75rem_1fr] gap-3 py-3.5">
                <span aria-hidden className="grid h-6 w-6 place-items-center rounded-full bg-ink text-xs font-bold text-white">{i + 1}</span>
                <div><p className="text-[15px] font-semibold">{t}</p><p className="mt-0.5 text-[13.5px] leading-relaxed text-ink/90">{b}</p></div>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
