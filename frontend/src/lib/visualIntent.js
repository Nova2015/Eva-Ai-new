// When a request that mentions a picture is not a request for a picture.
//
// Update 35c. From a real screenshot: "Creating image for excel sheet for all
// data set" produced a generated PNG that looks like a spreadsheet. The user
// wanted data and received a picture of data — unusable, unverifiable, and
// confidently wrong-looking.
//
// The image detector in Chat.js is a long chain of startsWith/includes grown
// over time, including typo variants. Two of its clauses are too broad:
//
//   t.includes('image for ')        matches "image for excel sheet"
//   IMAGE_SUBJECT_RE has 'diagram'  so "create a diagram" becomes a raster
//
// Rather than rewrite that chain and risk the typo handling people rely on,
// these are guards placed in front of it. Both answer the same question: is
// there a better artifact than a picture for what was asked?
//
// WHY THIS MATTERS BEYOND TIDINESS. A raster image cannot be checked. A
// spreadsheet can be opened and its cells compared; a chart's values can be
// traced to the source rows; a mermaid diagram is text whose structure is
// visible. When any of those will do, a picture is the one option that makes
// the answer unverifiable.

// Artifacts with their own verified path. If one of these is what was asked
// for, the image generator must not take the message.
const DATA_ARTIFACT_RE =
  /\b(excel|xlsx|spreadsheet|workbook|csv|\.xls|pivot table|google sheet)\b/i;

// A chart of real numbers belongs to the chart tool, which checks every value
// against the data. "chart" alone is deliberately included; a picture of a
// chart is never more useful than a chart.
const CHART_ARTIFACT_RE =
  /\b(bar chart|line chart|pie chart|scatter plot|graph of|chart of|chart from)\b/i;

// Structures mermaid renders, and can be read as text afterwards.
const STRUCTURED_DIAGRAM_RE =
  /\b(flow ?chart|flow diagram|sequence diagram|class diagram|er diagram|entity[- ]relationship|state diagram|state machine|org(?:ani[sz]ation(?:al)?)? chart|architecture diagram|system design|decision tree|process (?:flow|diagram|map)|mind ?map|use case diagram|workflow diagram|data flow)\b/i;

// Words that mean the user genuinely wants a rendered picture — an aesthetic
// artifact, not a structure. These override the diagram preference, because
// someone asking for a poster of a flowchart wants a poster.
const AESTHETIC_RE =
  /\b(photo|photograph|realistic|render|3d|artwork|illustration|painting|poster|wallpaper|logo|concept art|sketch of|cartoon|anime|banner|thumbnail)\b/i;

export function wantsDataArtifact(text) {
  const s = String(text || '');
  return DATA_ARTIFACT_RE.test(s) || CHART_ARTIFACT_RE.test(s);
}

export function wantsStructuredDiagram(text) {
  const s = String(text || '');
  if (!STRUCTURED_DIAGRAM_RE.test(s)) return false;
  // "make a poster of our process flow" is a poster.
  return !AESTHETIC_RE.test(s);
}

// The single question Chat.js asks: may the image generator take this message?
export function imageGeneratorMayHandle(text) {
  const s = String(text || '');
  if (!s.trim()) return false;
  if (wantsDataArtifact(s)) return false;
  if (wantsStructuredDiagram(s)) return false;
  return true;
}

// Shown under a generated image. An image is the one artifact here whose
// contents cannot be checked against anything, and saying so is more honest
// than letting a plausible-looking diagram be read as fact.
export const UNVERIFIED_IMAGE_NOTE =
  'Generated illustration — the details in it are not checked against any source.';
