from django.contrib.postgres.search import SearchQuery, SearchRank, TrigramWordSimilarity
from django.db.models import F, Q, Value
from django.db.models.functions import Greatest

TYPO_THRESHOLD = 0.4


def search_products(qs, q):
    """Full-text search (German stemming) plus trigram similarity for typos and word starts."""
    q = q.strip()[:100]
    if not q:
        return qs
    query = SearchQuery(q, config="german", search_type="websearch")
    return (
        qs.annotate(
            rank=SearchRank(F("search_vector"), query),
            similarity=Greatest(TrigramWordSimilarity(q, "name"), TrigramWordSimilarity(q, "supplier__name")),
        )
        .filter(Q(search_vector=query) | Q(similarity__gte=TYPO_THRESHOLD) | Q(name__icontains=q))
        .annotate(score=F("rank") + F("similarity") + Value(0.0))
        .order_by("-score", "name")
    )
