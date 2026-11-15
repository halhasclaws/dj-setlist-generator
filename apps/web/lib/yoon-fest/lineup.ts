// Yoon Fest printed lineup (poster columns: after-midnight slots stay under the
// previous day). End times are the next printed start. Keyed by set slug.
type Slot = readonly [slug: string, name: string, day: "Thu" | "Fri" | "Sat" | "Sun" | "Mon", start: string, end: string];

const LINEUP: readonly Slot[] = [
  ["yoon-fest-tompson-jake-cattani-partial", "Tompson & Jake Cattani", "Fri", "16:00", "18:00"],
  ["yoon-fest-tj-alfano-partial", "TJ Alfano", "Fri", "18:00", "19:30"],
  ["yoon-fest-john-manhard-teak-makai-partial", "John Manhard & Teak Makai", "Fri", "20:30", "22:00"],
  ["yoon-fest-choice-friday-mean-gaps-v2", "Choice", "Fri", "22:00", "00:00"],
  ["yoon-fest-hank-friday-mean-gaps-v2", "Hank", "Fri", "00:00", "01:30"],
  ["yoon-fest-sydka-live-friday-mean-gaps-v2", "Sydka (LIVE)", "Fri", "01:30", "03:00"],
  ["yoon-fest-jake-mora-friday-mean-gaps-v2", "Jake Mora", "Fri", "03:00", "04:30"],
  ["yoon-fest-honeydu-saturday-mean-gaps-v2", "Honeydü", "Sat", "04:30", "06:00"],
  ["yoon-fest-artur-saturday-mean-gaps-v2", "Artur", "Sat", "06:00", "07:30"],
  ["yoon-fest-airgordon-saturday-mean-gaps-v2", "Airgordon", "Sat", "07:30", "09:00"],
  ["yoon-fest-hunter-foshee-saturday-mean-gaps-v2", "Hunter Foshee", "Sat", "09:00", "10:30"],
  ["yoon-fest-barbie-fish-santiago-gammelli-saturday-mean-gaps-v2", "Barbie Fish & Santiago Gammelli", "Sat", "10:30", "12:30"],
  ["yoon-fest-pily-saturday-mean-gaps-v2", "Pily", "Sat", "12:30", "14:00"],
  ["yoon-fest-crypt-kreepers-partial", "Crypt Kreepers", "Sat", "14:00", "16:00"],
  ["yoon-fest-kana-hishiya-partial", "Kana Hishiya", "Sat", "16:00", "17:30"],
  ["yoon-fest-jay-dee-saturday", "Jay Dee", "Sat", "17:30", "19:00"],
  ["yoon-fest-doza-lawnchair-generals-saturday", "Doza (Lawnchair Generals)", "Sat", "19:00", "21:00"],
  ["yoon-fest-adam-rose-miro-saturday", "Adam Rose & Miro", "Sat", "21:00", "23:00"],
  ["yoon-fest-sinead-saturday", "Sinéad", "Sat", "23:00", "00:30"],
  // Revised order (Krane before Donald), not the poster's.
  ["yoon-fest-krane-saturday", "Krane", "Sat", "00:30", "02:00"],
  ["yoon-fest-donald-saturday-night", "Donald", "Sat", "02:00", "04:00"],
  ["yoon-fest-deep-house-dad-capes-sunday", "Deep House Dad & Capes", "Sun", "04:00", "05:30"],
  ["yoon-fest-max-coletto-hazy-sunday", "Max Coletto & Hazy", "Sun", "05:30", "07:00"],
  ["yoon-fest-sky-rivers-adam-rose-sunday", "Sky Rivers & Adam Rose", "Sun", "07:00", "09:30"],
  ["yoon-fest-4yo4u-jahnsen-local-jerry-sunday", "4Yo4U, Jahnsen, & Local Jerry", "Sun", "09:30", "11:30"],
  ["yoon-fest-grisha-sunday", "Grisha", "Sun", "11:30", "13:30"],
  ["yoon-fest-highkin-sunday", "Highkin", "Sun", "13:30", "15:30"],
  ["yoon-fest-jackson-sunday-pilot", "Jackson Algeo", "Sun", "15:30", "17:30"],
  ["yoon-fest-halo-varga-sunday", "Halo Varga", "Sun", "17:30", "19:00"],
  ["yoon-fest-mungo-sound-machine-sunday", "Mungo Sound Machine", "Sun", "19:00", "20:30"],
  ["yoon-fest-brett-johnson-sunday", "Brett Johnson", "Sun", "20:30", "22:30"],
  ["yoon-fest-danny-daze-sunday", "Danny Daze", "Sun", "22:30", "00:30"],
  ["yoon-fest-dylan-payne-partial", "Dylan Payne", "Sun", "00:30", "02:30"],
];

const clock = (value: string) => {
  const [hours, minutes] = value.split(":").map(Number);
  return { text: `${hours % 12 || 12}:${String(minutes).padStart(2, "0")}`, half: hours < 12 ? "AM" : "PM" };
};

/** "Jackson Algeo (Sun. 3:30 - 5:30 PM)"; the AM/PM shows once when both ends share it. */
export function formatLineupTitle([, name, day, start, end]: Slot): string {
  const from = clock(start); const to = clock(end);
  const range = from.half === to.half ? `${from.text} - ${to.text} ${to.half}` : `${from.text} ${from.half} - ${to.text} ${to.half}`;
  return `${name} (${day}. ${range})`;
}

const TITLES = new Map(LINEUP.map((slot) => [slot[0], formatLineupTitle(slot)]));
export const lineupTitle = (slug: string): string | null => TITLES.get(slug) ?? null;
