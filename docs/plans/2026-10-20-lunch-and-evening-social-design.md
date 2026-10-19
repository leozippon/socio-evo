# Fixed lunch and open evenings

The opt-in `activities` and `realtime` community configurations use the Riverside Restaurant as the daily lunch destination. At noon, residents finish an operation or move already underway, then travel there; late arrival still completes that day's lunch. Lunch has no meal action, hunger state or charge.

At 18:00, residents in Work or long Rest choose their evening activity again. Conversation already underway can continue. Residents choose their own destination and company. Appointment invitations reuse the existing response flow; confirmed residents receive a departure reminder based on walking time, which may wake Rest but never sends them automatically. Declined or superseded invitations do not trigger the old reminder.

Conversation membership follows event time: joining grants access to speech from that point onward, and leaving ends future delivery. In a group, other members can continue after someone leaves. The default `scenes` and `independent` schedulers keep their existing behavior.
