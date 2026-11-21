"""Content for the static information pages (/pages/<slug>).

Text may contain ``{company}``, ``{address}``, ``{phone}``, ``{email}``, ``{gstin}``,
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
                    "We started {store} in Mumbai with a simple idea: a haat (the weekly village "
                    "market) where you can trust the seller, compare prices and pick the best for "
                    "your family. Today we ship to over 19,000 PIN codes across India.",
                    "Every product listed is checked by our catalogue team. Descriptions are "
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
            ("Registered office", ["{company}, {address}. GSTIN {gstin}."]),
        ],
    },
    "careers": {
        "title": "Careers at {store}",
        "lead": "We're a small team building a big marketplace. Come build it with us.",
        "sections": [
            (
                "Open roles",
                [
                    "Senior Backend Engineer (Python) · Mumbai / Remote",
                    "Category Manager, Audio & Wearables · Mumbai",
                    "Customer Experience Associate (Hindi, Tamil or Bengali) · Bengaluru",
                    "Warehouse Operations Lead · Bhiwandi",
                ],
            ),
            ("How to apply", ["Write to {email} with the role in the subject line."]),
        ],
    },
    "sell": {
        "title": "Sell on {store}",
        "lead": "Reach lakhs of customers with zero listing fees for the first 90 days.",
        "sections": [
            (
                "Why sell with us",
                [
                    "Payments settled every 7 days, straight to your bank account.",
                    "Fulfilment from our warehouses, or ship it yourself with our courier rates.",
                    "AI-powered listing help: our ShopCrew assistant drafts SEO copy and pricing "
                    "suggestions from your reviews and the market.",
                ],
            ),
            (
                "What you need",
                [
                    "GSTIN, PAN, a bank account in your business name, and at least one product.",
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
                    "Orders during the festive week grew 3x year on year, with Tier-2 cities "
                    "contributing more than half of all orders.",
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
                    "Metro cities (Mumbai, Delhi NCR, Bengaluru, Chennai, Hyderabad, Kolkata, "
                    "Pune, "
                    "Ahmedabad): 1–2 business days.",
                    "Rest of India: 3–6 business days. North-East and island territories may take "
                    "up to 8 days.",
                    "Enter your PIN code on any product page to see the exact delivery date.",
                ],
            ),
            (
                "Cash on delivery",
                [
                    "Available on all PIN codes we serve, for orders up to $700. A ${cod_fee} "
                    "handling fee applies.",
                ],
            ),
            (
                "Tracking",
                [
                    "Once your order ships you'll see the courier and AWB number under "
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
                    "UPI: 1–2 business days · Cards and net banking: 5–7 business days · Cash on "
                    "delivery orders: refunded to your bank account or UPI ID within 3 days of "
                    "pickup.",
                ],
            ),
        ],
    },
    "help": {
        "title": "Help centre",
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
                "UPI refunds take 1–2 business days; cards and net "
                "banking take 5–7 business days after we receive the return.",
            ),
            (
                "Is cash on delivery available?",
                "Yes, on every PIN code we deliver to. A ${cod_fee} handling fee applies.",
            ),
            (
                "Are the products genuine?",
                "Every product is sourced directly from the brand or "
                "its authorised distributor and comes with the manufacturer's warranty and a GST "
                "invoice.",
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
                "How do I get a GST invoice?",
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
        "lead": "Last updated 1 November 2026.",
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
                    "All prices are in US dollars and include taxes. We may cancel orders caused "
                    "by a pricing error and refund you in full.",
                ],
            ),
            (
                "4. Governing law",
                [
                    "These terms are governed by the laws of India. Courts in Mumbai have "
                    "exclusive jurisdiction.",
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
                    "Under the Digital Personal Data Protection Act, 2023 you can ask us for a "
                    "copy "
                    "of your data, correct it, or delete your account. Write to {email}.",
                ],
            ),
        ],
    },
    "grievance": {
        "title": "Grievance redressal",
        "lead": "As required by the Consumer Protection (E-Commerce) Rules, 2020.",
        "sections": [
            (
                "Grievance Officer",
                [
                    "Ms. Ananya Rao, Grievance Officer",
                    "{company}, {address}",
                    "Email: grievance@northcart.test · Phone: {phone}",
                    "Monday to Friday, 10 AM – 6 PM",
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
