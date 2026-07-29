import * as path from "node:path";
import { CfnOutput, Duration, Stack, StackProps } from "aws-cdk-lib";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import * as integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as sources from "aws-cdk-lib/aws-lambda-event-sources";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as sqs from "aws-cdk-lib/aws-sqs";
import { Construct } from "constructs";

export interface SlackAdapterStackProps extends StackProps {
  readonly adapterRoot: string;
  readonly appSlug: string;
  readonly harnessArn: string;
  readonly harnessQualifier: string;
  readonly allowedTeamId: string;
  readonly slackBotUserId?: string;
  readonly signingSecretArn?: string;
  readonly botTokenSecretArn?: string;
  readonly sessionHmacSecretArn?: string;
  readonly bundleDependencies?: boolean;
}

export class SlackAdapterStack extends Stack {
  constructor(scope: Construct, id: string, props: SlackAdapterStackProps) {
    super(scope, id, props);
    this.validateProps(props);

    const signingSecret = this.secret(
      "SlackSigningSecret",
      props.signingSecretArn,
      `${props.appSlug}/slack/signing-secret`,
      48,
    );
    const botTokenSecret = this.secret(
      "SlackBotToken",
      props.botTokenSecretArn,
      `${props.appSlug}/slack/bot-token`,
      64,
    );
    const sessionHmacSecret = this.secret(
      "SlackSessionHmacKey",
      props.sessionHmacSecretArn,
      `${props.appSlug}/slack/session-hmac-key`,
      64,
    );

    const deadLetterQueue = new sqs.Queue(this, "DeadLetterQueue", {
      queueName: `${props.appSlug}-slack-dlq.fifo`,
      fifo: true,
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      retentionPeriod: Duration.days(14),
    });
    const eventQueue = new sqs.Queue(this, "EventQueue", {
      queueName: `${props.appSlug}-slack-events.fifo`,
      fifo: true,
      contentBasedDeduplication: false,
      deduplicationScope: sqs.DeduplicationScope.MESSAGE_GROUP,
      fifoThroughputLimit: sqs.FifoThroughputLimit.PER_MESSAGE_GROUP_ID,
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      visibilityTimeout: Duration.minutes(6),
      deadLetterQueue: { queue: deadLetterQueue, maxReceiveCount: 5 },
    });

    const functionCode = this.lambdaCode(props);
    const ingress = new lambda.Function(this, "IngressFunction", {
      description: "Verify Slack Events API requests and enqueue them",
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      code: functionCode,
      handler: "ingress.handler.lambda_handler",
      timeout: Duration.seconds(5),
      memorySize: 256,
      environment: {
        QUEUE_URL: eventQueue.queueUrl,
        SIGNING_SECRET_ARN: signingSecret.secretArn,
        ALLOWED_TEAM_ID: props.allowedTeamId,
        SLACK_BOT_USER_ID: props.slackBotUserId ?? "",
      },
    });
    eventQueue.grantSendMessages(ingress);
    signingSecret.grantRead(ingress);

    const worker = new lambda.Function(this, "WorkerFunction", {
      description: "Invoke AgentCore Harness and stream the response to Slack",
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      code: functionCode,
      handler: "worker.handler.lambda_handler",
      timeout: Duration.minutes(5),
      memorySize: 512,
      environment: {
        HARNESS_ARN: props.harnessArn,
        HARNESS_QUALIFIER: props.harnessQualifier,
        BOT_TOKEN_SECRET_ARN: botTokenSecret.secretArn,
        SESSION_HMAC_SECRET_ARN: sessionHmacSecret.secretArn,
        HARNESS_MAX_ITERATIONS: "10",
        HARNESS_MAX_TOKENS: "8000",
        HARNESS_TIMEOUT_SECONDS: "240",
      },
    });
    botTokenSecret.grantRead(worker);
    sessionHmacSecret.grantRead(worker);
    worker.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "InvokePinnedAgentCoreHarness",
        actions: [
          "bedrock-agentcore:InvokeHarness",
          "bedrock-agentcore:InvokeAgentRuntime",
        ],
        resources: [
          props.harnessArn,
          `${props.harnessArn}/harness-endpoint/${props.harnessQualifier}`,
        ],
      }),
    );
    worker.addEventSource(
      new sources.SqsEventSource(eventQueue, {
        batchSize: 1,
        reportBatchItemFailures: true,
      }),
    );

    const api = new apigwv2.HttpApi(this, "SlackEventsApi", {
      apiName: `${props.appSlug}-slack-events`,
      description: "Public Slack ingress protected by Slack request signatures",
    });
    api.addRoutes({
      path: "/slack/events",
      methods: [apigwv2.HttpMethod.POST],
      integration: new integrations.HttpLambdaIntegration(
        "IngressIntegration",
        ingress,
      ),
    });

    new CfnOutput(this, "SlackRequestUrl", {
      value: `${api.apiEndpoint}/slack/events`,
    });
    new CfnOutput(this, "SigningSecretArn", { value: signingSecret.secretArn });
    new CfnOutput(this, "BotTokenSecretArn", { value: botTokenSecret.secretArn });
    new CfnOutput(this, "SessionHmacSecretArn", {
      value: sessionHmacSecret.secretArn,
    });
    new CfnOutput(this, "DeadLetterQueueUrl", {
      value: deadLetterQueue.queueUrl,
    });
  }

  private validateProps(props: SlackAdapterStackProps): void {
    const arn =
      /^arn:([^:]+):bedrock-agentcore:([^:]+):([^:]+):harness\/([A-Za-z0-9_-]+)$/.exec(
        props.harnessArn,
      );
    if (!arn || arn[2] !== this.region || arn[3] !== this.account) {
      throw new Error(
        "harnessArn must identify a Harness in this stack account and region",
      );
    }
    if (!/^[A-Za-z][A-Za-z0-9_]{0,47}$/.test(props.harnessQualifier)) {
      throw new Error("harnessQualifier contains unsupported characters");
    }
    if (!/^T[A-Z0-9]+$/.test(props.allowedTeamId)) {
      throw new Error("allowedTeamId must be a Slack team ID");
    }
  }

  private secret(
    id: string,
    importedArn: string | undefined,
    secretName: string,
    length: number,
  ): secretsmanager.ISecret {
    if (importedArn) {
      return secretsmanager.Secret.fromSecretCompleteArn(this, id, importedArn);
    }
    return new secretsmanager.Secret(this, id, {
      secretName,
      description: `${id} for the Slack adapter`,
      generateSecretString: {
        passwordLength: length,
        excludePunctuation: true,
      },
    });
  }

  private lambdaCode(props: SlackAdapterStackProps): lambda.Code {
    if (props.bundleDependencies === false) {
      return lambda.Code.fromAsset(path.join(props.adapterRoot, "src"));
    }
    return lambda.Code.fromAsset(props.adapterRoot, {
      bundling: {
        image: lambda.Runtime.PYTHON_3_13.bundlingImage,
        command: [
          "bash",
          "-c",
          [
            "python -m pip install",
            "-r /asset-input/requirements-lambda.txt",
            "-t /asset-output",
            "&& cp -R /asset-input/src/. /asset-output/",
          ].join(" "),
        ],
      },
      exclude: [".venv", ".pytest_cache", ".ruff_cache", "infra", "tests"],
    });
  }
}
