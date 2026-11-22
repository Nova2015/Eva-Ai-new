import ReviewBadge from './ReviewBadge';
import RuntimeBadge from './RuntimeBadge';

// Review and runtime badges, gated by the same provenance rule as the audit
// panel. They are answer metadata, and metadata is shown only when asked for.
//
// Kept as its own component, separate from ProvenanceDetails, because the two
// render in different places: badges sit above the answer text inside the
// message bubble, the panel sits below the bubble. Merging them would move one
// of them.
export default function ProvenanceBadges({ show, review, runtime, streaming }) {
  if (!show || streaming) return null;
  if (!review && !runtime) return null;

  return (
    <div>
      {review ? <ReviewBadge review={review} /> : null}
      {runtime ? <RuntimeBadge runtime={runtime} /> : null}
    </div>
  );
}
