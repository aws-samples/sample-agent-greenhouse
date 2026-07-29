import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { SlackAdapterStack } from "../lib/slack-adapter-stack";

const HARNESS_ARN =
  "arn:aws:bedrock-agentcore:us-east-1:111122223333:harness/SampleHarness-abcdefghij";

function template(): Template {
  const app = new cdk.App();
  const stack = new SlackAdapterStack(app, "TestStack", {
    env: { account: "111122223333", region: "us-east-1" },
    adapterRoot: path.resolve(__dirname, "../.."),
    appSlug: "__APP_SLUG__",
    harnessArn: HARNESS_ARN,
    harnessQualifier: "PROD",
    allowedTeamId: "TTEST",
    bundleDependencies: false,
  });
  return Template.fromStack(stack);
}

test("creates the small asynchronous Slack pipeline", () => {
  const result = template();
  result.resourceCountIs("AWS::Lambda::Function", 2);
  result.resourceCountIs("AWS::SQS::Queue", 2);
  result.resourceCountIs("AWS::SecretsManager::Secret", 3);
  result.resourceCountIs("AWS::DynamoDB::Table", 0);
  result.hasResourceProperties("AWS::ApiGatewayV2::Route", {
    RouteKey: "POST /slack/events",
  });
  result.hasResourceProperties("AWS::Lambda::EventSourceMapping", {
    BatchSize: 1,
    FunctionResponseTypes: ["ReportBatchItemFailures"],
  });
});

test("pins Harness permissions and separates Slack secrets", () => {
  const result = template();
  result.hasResourceProperties("AWS::IAM::Policy", {
    PolicyDocument: {
      Statement: Match.arrayWith([
        Match.objectLike({
          Action: [
            "bedrock-agentcore:InvokeHarness",
            "bedrock-agentcore:InvokeAgentRuntime",
          ],
          Resource: [
            HARNESS_ARN,
            `${HARNESS_ARN}/harness-endpoint/PROD`,
          ],
        }),
      ]),
    },
  });

  const functions = result.findResources("AWS::Lambda::Function");
  const ingress = Object.values(functions).find(
    (resource: any) =>
      resource.Properties.Handler === "ingress.handler.lambda_handler",
  ) as any;
  expect(
    ingress.Properties.Environment.Variables.BOT_TOKEN_SECRET_ARN,
  ).toBeUndefined();
  expect(
    ingress.Properties.Environment.Variables.SESSION_HMAC_SECRET_ARN,
  ).toBeUndefined();
});
