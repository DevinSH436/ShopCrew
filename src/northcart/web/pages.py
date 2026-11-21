"""Content for the static information pages (/pages/<slug>).

Text may contain ``{company}``, ``{address}``, ``{phone}``, ``{email}``, ``{tax_id}``,
``{store}``, ``{free_ship}``, ``{ship_fee}``, ``{cod_fee}`` and ``{returns}`` placeholders,
which the template fills from the store settings.
"""

from __future__ import annotations

PAGES: dict[str, dict] = {
    "about": {
        "title": "About {store}",
        "lead": "{store} is an online marketplace for everyday tech, home and lifestyle "
        "products: fairly priced, honestly described and delivered fast.",
        "sections": [
            (
                "Our story",
                [
                    "We started {store} in Columbus, Ohio with a simple idea: a neighborhood "
                    "store online, where you can trust the seller, compare prices and pick the "
                    "best for your family. Today we ship to all 50 states.",
                    "Every product listed is checked by our catalog team. Descriptions are "
                    "written from real customer feedback, and we never list a feature a product "
                    "doesn't have.",
                ],
            ),
            (
                "What we stand for",
                [
                    "Fair prices: we track the market daily so you don't have to.",
                    "Honest listings: real reviews, verified purchase badges, no paid ratings.",
                    "Easy returns: {returns}-day returns on most products, refunds in 5–7 days.",
                ],
            ),
            ("Headquarters", ["{company}, {address}. EIN {tax_id}."]),
        ],
    },
    "careers": {
        "title": "Careers at {store}",
        "lead": "We're a small team building a big marketplace. Come build it with us.",
        "sections": [
            (
                "Open roles",
                [
                    "Senior Backend Engineer (Python) · Columbus, OH / Remote (US)",
                    "Category Manager, Audio & Wearables · Columbus, OH",
                    "Customer Experience Associate (English and Spanish) · Remote (US)",
                    "Warehouse Operations Lead · Groveport, OH",
                ],
            ),
            ("How to apply", ["Write to {email} with the role in the subject line."]),
        ],
    },
    "sell": {
        "title": "Sell on {store}",
        "lead": "Reach millions of shoppers with zero listing fees for the first 90 days.",
        "sections": [
            (
                "Why sell with us",
                [
                    "Payments settled every 7 days, straight to your bank account.",
                    "Fulfillment from our warehouses, or ship it yourself with our carrier rates.",
                    "AI-powered listing help: our ShopCrew assistant drafts SEO copy and pricing "
                    "suggestions from your reviews and the market.",
                ],
            ),
            (
                "What you need",
                [
                    "An EIN (or SSN for sole proprietors), a US bank account in your business "
                    "name, and at least one product.",
                ],
            ),
        ],
    },
    "press": {
        "title": "Press releases",
        "lead": "News and announcements from {store}.",
        "sections": [
            (
                "Nov 2026: Big Holiday Sale breaks records",
                [
                    "Orders during Black Friday week grew 3x year over year, with shoppers "
                    "outside the big metro areas placing more than half of all orders.",
                ],
            ),
            (
                "Aug 2026: AI review summaries launch",
                [
                    "Product pages now show a 'Customers say' summary written by our AI review "
                    "analyst from verified customer reviews.",
                ],
            ),
            ("Media contact", ["press@northcart.test"]),
        ],
    },
    "shipping": {
        "title": "Shipping & delivery",
        "lead": "Free delivery on orders of ${free_ship} and above. "
        "Below that, a flat ${ship_fee}.",
        "sections": [
            (
                "Delivery times",
                [
                    "Major metro areas (New York, Chicago, Los Angeles, San Francisco, Seattle, "
                    "Houston, Philadelphia, Washington DC) and the Midwest: 1–2 business days.",
                    "Rest of the continental US: 3–5 business days. Alaska and Hawaii may take "
                    "up to 8 days.",
                    "Enter your ZIP code on any product page to see the exact delivery date.",
                ],
            ),
            (
                "Pay on delivery",
                [
                    "Available for orders up to $700: pay the driver by card or cash. A "
                    "${cod_fee} handling fee applies.",
                ],
            ),
            (
                "Tracking",
                [
                    "Once your order ships you'll see the carrier and tracking number under "
                    "Your Orders.",
                ],
            ),
        ],
    },
    "returns": {
        "title": "Returns, refunds & cancellation",
        "lead": "Changed your mind? Most items can be returned within {returns} days of delivery.",
        "sections": [
            (
                "Cancelling an order",
                [
                    "You can cancel any order from Your Orders until it is shipped. Prepaid orders "
                    "are refunded in full to the original payment method.",
                ],
            ),
            (
                "Returning an item",
                [
                    "Open the order, choose 'Return items' and pick a reason. We'll arrange a "
                    "free pickup within 2 business days.",
                    "Items must be unused, with original packaging and accessories. Personal care "
                    "items and opened innerwear cannot be returned for hygiene reasons.",
                ],
            ),
            (
                "Refund timelines",
                [
                    "PayPal: 1–2 business days · Cards and bank accounts: 5–7 business days · "
                    "Pay-on-delivery orders: refunded to your bank account within 3 days of "
                    "pickup.",
                ],
            ),
        ],
    },
    "help": {
        "title": "Help center",
        "lead": "Answers to the questions we hear most. Still stuck? Call {phone}.",
        "faq": [
            (
                "Where is my order?",
                "Go to Your Orders and open the order. You'll see each step "
                "from 'Order placed' to 'Delivered', plus the courier and tracking number once it "
                "ships.",
            ),
            (
                "How do I cancel an order?",
                "Open the order in Your Orders and click 'Cancel "
                "order'. You can cancel until the order ships.",
            ),
            (
                "When will I get my refund?",
                "PayPal refunds take 1–2 business days; cards and bank "
                "accounts take 5–7 business days after we receive the return.",
            ),
            (
                "Can I pay on delivery?",
                "Yes, for orders up to $700. A ${cod_fee} handling fee applies.",
            ),
            (
                "Are the products genuine?",
                "Every product is sourced directly from the brand or "
                "its authorized distributor and comes with the manufacturer's warranty and an "
                "itemized invoice.",
            ),
            (
                "How do I use a coupon?",
                "Enter the code in your cart or on the checkout page. "
                "Only one coupon can be used per order.",
            ),
            (
                "Can I change my delivery address?",
                "Before the order ships, contact us at "
                "{phone} and we'll update it. After shipping, the address can't be changed.",
            ),
            (
                "How do I get an invoice?",
                "Open the order and click 'Invoice'. You can print it or save it as a PDF.",
            ),
        ],
        "sections": [],
    },
    "contact": {
        "title": "Contact us",
        "lead": "We're here 9 AM – 9 PM, every day.",
        "contact": True,
        "sections": [
            ("Call", ["{phone} (toll free)"]),
            ("Email", ["{email}"]),
            ("Write to us", ["{company}, {address}"]),
        ],
    },
    "terms": {
        "title": "Terms of use",
        "lead": "Last updated November 1, 2026.",
        "sections": [
            (
                "1. About these terms",
                [
                    "This website is operated by {company} ('{store}', 'we'). By using it you "
                    "agree to these terms.",
                ],
            ),
            (
                "2. Your account",
                [
                    "You're responsible for keeping your password safe and for all activity on "
                    "your account. You must be 18 or older, or use the site with a parent's "
                    "supervision.",
                ],
            ),
            (
                "3. Prices and availability",
                [
                    "All prices are in US dollars and include sales tax. We may cancel orders "
                    "caused "
                    "by a pricing error and refund you in full.",
                ],
            ),
            (
                "4. Governing law",
                [
                    "These terms are governed by the laws of the State of Ohio. Courts in "
                    "Franklin County, Ohio have exclusive jurisdiction.",
                ],
            ),
        ],
    },
    "privacy": {
        "title": "Privacy policy",
        "lead": "We collect only what we need to deliver your orders, and we never sell your data.",
        "sections": [
            (
                "What we collect",
                [
                    "Your name, phone, email and delivery addresses; your orders; and basic device "
                    "information to keep the site secure.",
                ],
            ),
            (
                "Payments",
                [
                    "Card details are entered on our payment partner's secure page and are never "
                    "stored on our servers.",
                ],
            ),
            (
                "Your rights",
                [
                    "Depending on your state (for example under the California Consumer Privacy "
                    "Act), you can ask us for a copy of your data, correct it, or delete your "
                    "account. Write to {email}.",
                ],
            ),
        ],
    },
    "grievance": {
        "title": "Complaints",
        "lead": "Not happy with an order or with us? Tell us and we'll make it right.",
        "sections": [
            (
                "Customer Advocate",
                [
                    "Dana Brooks, Customer Advocate",
                    "{company}, {address}",
                    "Email: complaints@northcart.test · Phone: {phone}",
                    "Monday to Friday, 9 AM – 5 PM ET",
                ],
            ),
            (
                "Timelines",
                [
                    "We acknowledge every complaint within 48 hours and resolve it within one "
                    "month of receipt.",
                ],
            ),
        ],
    },
}
