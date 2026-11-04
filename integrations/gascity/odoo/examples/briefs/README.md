# Rewrite Odoo tasks as behavior

A brief states the problem, acceptance criteria, approach as behavior, and scope.
Keep implementation choices for the later specification step. Preserve uncertain
business decisions as open questions for human review.

Prescriptive source text:

> Add a delivered quantity field to the shipment model and override its validation
> method in the delivery source file.

The [rewritten brief](partial-delivery.json) describes the quantities a dispatcher
sees after successive shipments. It includes a cancellation case and asks how
returns should affect the result. It leaves storage, calculation and extension
choices to implementation.

Another prescriptive request:

> Add a daily scheduled action that searches the order model and sends a reminder.

Behavioral rewrite:

> Each morning, a salesperson sees which promised deliveries are overdue. Each
> customer receives at most one reminder per overdue delivery per day. Cancelled
> deliveries and customers who opted out receive none. Changing delivery dates or
> customer preferences takes effect before the next reminder.

These are example requirements for the forthcoming Odoo delivery pack. They do
not establish that an Odoo workflow has been implemented or approved.
