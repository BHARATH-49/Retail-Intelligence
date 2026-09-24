# Retail Intelligence

An ML-powered retail decision-support platform for small-scale businesses.

The system combines demand forecasting, contextual demand analysis, local business adaptation, opportunity discovery, and purchase comparison to help store owners make better inventory and purchasing decisions.

# Project Goals

The system is designed to answer five practical questions:

1. What am I likely to need?
   - Forecast product demand using historical sales data.

2. Why might demand change?
   - Use contextual factors such as weather, holidays, events, promotions, and other available demand-related signals.

3. What could I consider stocking?
   - Discover locally relevant movies, shows, events, and trends and identify products associated with them.

4. How do competitors affect my demand?
   - Record competitor activity and progressively learn its relationship with the store's own sales.

5. Where should I purchase the required products?
   - Compare online and manually entered local supplier prices and generate a final purchase list.

# Core Components

 1. Demand Forecasting

Machine learning models trained on historical retail sales data to estimate future product demand.

2. Context-Aware Demand

Machine learning models that incorporate available contextual information such as:

- Weather
- Public holidays
- Events
- Promotions
- Other observable demand disruptions

3. Opportunity Discovery

A retrieval and recommendation system rather than a forecasting model.

It will:

- Identify locally relevant movies/shows and events.
- Search for products associated with those trends.
- Check whether relevant products can be purchased from retailers.
- Compare opportunities against the store's product catalogue and customer interests.
- Incorporate owner and customer feedback over time.

4. Competitor Effect

The system records competitor status alongside the store's sales history.

As sufficient local observations accumulate, the system can learn relationships such as:

Competitor closed --> Change in store demand --> Local competitor effect --> Use it later

5. Purchase Comparison

For products recommended by the system:

Search available online products.
Compare prices and quantities.
Normalize prices where necessary.
Allow the owner to enter local supplier prices.
Compare local and online purchasing options.
Generate a final buy list for owner approval

# Workflow Overview

1. Restock Optimization

This pipeline processes historical business data to predict inventory demand and generate precise restock lists.

               BUSINESS DATA
                     |
        +------------+------------+
        |            |            |
     Products     Inventory   Customers
        |            |            |
        +------------+------------+
                     |
                     v
            DEMAND FORECASTING
                   (ML)
                     |
                     v
            CONTEXT ANALYSIS
                   (ML)
                     |
                     v
               FINAL DEMAND
                     |
                     v
                RESTOCK LIST


2. Opportunity Sourcing

This pipeline captures external trends, local events, and customer sentiment to discover and source new, profitable products.

Movies / Shows -------+
Local Events ---------+
Customer Interests ---+
Customer Feedback ----+
                      |
                      v
             OPPORTUNITY ENGINE
                  (Search)
                      |
                      v
             PRODUCT DISCOVERY
                      |
                      v
             PURCHASE COMPARISON
                      |
                      v
                FINAL BUY LIST


# Machine Learning Strategy

The project will initially use publicly available datasets for training.

As the system is used by a business, locally collected data can be incorporated through periodic model updates and evaluation.

        Public Data
            ↓
       Initial Model
            ↓
      Business Usage
            ↓
Local Sales / Inventory / Feedback
            ↓
     Model Evaluation
            ↓
    Periodic Model Update

The system will not attempt to retrain models after every individual transaction.

# Development Approach

The project will be developed incrementally:

Data acquisition and validation
Exploratory data analysis
Demand forecasting
Context-aware forecasting
Backend and database
Local model adaptation
Competitor learning
Opportunity discovery
Customer feedback
Purchase comparison
Testing and containerization
Final interface and deployment
Initial Data Strategy

The first model will be developed using a public retail sales dataset.

External datasets/APIs will be integrated separately for contextual information such as weather and other events.

The project will prioritize available and usable data coverage over attempting to find a single dataset containing every required feature.

# Technology Stack
- Python
- FastAPI
- PostgreSQL
- Redis
- Scikit-learn / PyTorch
- Pandas
- Docker
- REST APIs
- Git / GitHub


