#!/bin/bash

###############################################################################
# West End Scraper - AWS Deployment Script
#
# This script deploys the West End theatre scraper to AWS using SAM.
#
# Usage:
#   ./deploy.sh [dev|prod] [options]
#
# Options:
#   --guided    Run guided deployment (first time setup)
#   --skip-build Skip building the Docker image
#
# Prerequisites:
#   - AWS CLI configured with credentials
#   - AWS SAM CLI installed
#   - Docker running (for building Lambda container)
#   - Anthropic API key stored in AWS Secrets Manager
###############################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
ENVIRONMENT=${1:-dev}
GUIDED=false
SKIP_BUILD=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --guided)
            GUIDED=true
            shift
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
    esac
done

# Validate environment
if [[ ! "$ENVIRONMENT" =~ ^(dev|prod)$ ]]; then
    echo -e "${RED}Error: Environment must be 'dev' or 'prod'${NC}"
    echo "Usage: ./deploy.sh [dev|prod] [options]"
    exit 1
fi

echo -e "${GREEN}🚀 Deploying West End Scraper to AWS (${ENVIRONMENT})${NC}\n"

# Check prerequisites
echo "📋 Checking prerequisites..."

if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI not found. Please install it first.${NC}"
    exit 1
fi

if ! command -v sam &> /dev/null; then
    echo -e "${RED}Error: AWS SAM CLI not found. Please install it first.${NC}"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo -e "${RED}Error: Docker is not running. Please start Docker first.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Prerequisites check passed${NC}\n"

# Get AWS account ID and region
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=$(aws configure get region || echo "us-east-1")

echo "AWS Account ID: $AWS_ACCOUNT_ID"
echo "AWS Region: $AWS_REGION"
echo ""

# Stack name
STACK_NAME="west-end-scraper-${ENVIRONMENT}"

# Check if Anthropic API key exists in Secrets Manager
SECRET_NAME="west-end-scraper/anthropic-api-key"
echo "🔑 Checking for Anthropic API key in Secrets Manager..."

if ! aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$AWS_REGION" &> /dev/null; then
    echo -e "${YELLOW}Warning: Secret '$SECRET_NAME' not found in Secrets Manager${NC}"
    echo ""
    read -p "Enter your Anthropic API key: " -s ANTHROPIC_API_KEY
    echo ""

    echo "Creating secret in Secrets Manager..."
    aws secretsmanager create-secret \
        --name "$SECRET_NAME" \
        --description "Anthropic API key for West End scraper" \
        --secret-string "$ANTHROPIC_API_KEY" \
        --region "$AWS_REGION"

    echo -e "${GREEN}✓ Secret created${NC}\n"
else
    echo -e "${GREEN}✓ Secret found${NC}\n"
fi

# Build and deploy
if [ "$SKIP_BUILD" = false ]; then
    echo "🔨 Building SAM application..."
    sam build --use-container
    echo -e "${GREEN}✓ Build complete${NC}\n"
else
    echo -e "${YELLOW}⏭️  Skipping build${NC}\n"
fi

# Prepare deploy parameters
DEPLOY_PARAMS=(
    --stack-name "$STACK_NAME"
    --region "$AWS_REGION"
    --capabilities CAPABILITY_IAM
    --parameter-overrides
        "Environment=${ENVIRONMENT}"
        "AnthropicApiKeySecretName=${SECRET_NAME}"
        "ScheduleEnabled=$([ "$ENVIRONMENT" = "prod" ] && echo "true" || echo "false")"
)

# Add email if provided
if [ ! -z "$ALERT_EMAIL" ]; then
    DEPLOY_PARAMS+=(
        "AlertEmail=${ALERT_EMAIL}"
    )
fi

# Deploy
echo "🚢 Deploying to AWS..."

if [ "$GUIDED" = true ]; then
    sam deploy --guided
else
    sam deploy "${DEPLOY_PARAMS[@]}"
fi

echo -e "${GREEN}✓ Deployment complete!${NC}\n"

# Get stack outputs
echo "📊 Stack Outputs:"
aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
    --output table

# Get S3 bucket name for sites config
BUCKET_NAME=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`SitesConfigBucket`].OutputValue' \
    --output text)

echo ""
echo -e "${YELLOW}📝 Next steps:${NC}"
echo "1. Upload your sites configuration to S3:"
echo "   aws s3 cp sites/west_end.json s3://${BUCKET_NAME}/west_end.json"
echo ""
echo "2. Test the scraper manually:"
echo "   aws sqs send-message \\"
echo "     --queue-url <QueueUrl> \\"
echo "     --message-body '{\"show_name\":\"Hamilton\",\"url\":\"...\",\"selectors\":{}}'"
echo ""
echo "3. View logs:"
echo "   aws logs tail /aws/lambda/west-end-scraper-${ENVIRONMENT} --follow"
echo ""
echo -e "${GREEN}🎉 Deployment successful!${NC}"
