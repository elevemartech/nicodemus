from agent.tools.search_knowledge_base import search_knowledge_base

TOOLS_REGISTRY = [
    generate_financial_report,
    generate_enrollments_report,
    generate_requests_report,
    list_faqs,
    analyze_faqs,
    build_faq_plan,
    execute_faq_plan,
    search_knowledge_base,  # ← linha nova
]